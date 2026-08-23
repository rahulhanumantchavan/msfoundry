package webhook

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	admissionv1 "k8s.io/api/admission/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	"github.com/contoso/agent-identity-operator/internal/agentid"
	"github.com/contoso/agent-identity-operator/internal/blueprint"
)

const testGUID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

func testScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	s := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(s); err != nil {
		t.Fatalf("add scheme: %v", err)
	}
	return s
}

func agentNamespace(name string, enabled string) *corev1.Namespace {
	return &corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{
			Name:   name,
			Labels: map[string]string{agentid.NamespaceLabelKey: enabled},
		},
	}
}

func request(t *testing.T, pod *corev1.Pod) admission.Request {
	t.Helper()
	raw, err := json.Marshal(pod)
	if err != nil {
		t.Fatalf("marshal pod: %v", err)
	}
	return admission.Request{
		AdmissionRequest: admissionv1.AdmissionRequest{
			UID:       "test-uid",
			Namespace: pod.Namespace,
			Operation: admissionv1.Create,
			Object:    runtime.RawExtension{Raw: raw},
		},
	}
}

func agentPod() *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Namespace:   "agents",
			Annotations: map[string]string{agentid.AnnotationKey: testGUID},
		},
		Spec: corev1.PodSpec{
			Containers: []corev1.Container{{Name: "agent", Image: "busybox"}},
		},
	}
}

// stubAPI returns a server that always replies with the given status code and
// records how many times it was called.
func stubAPI(t *testing.T, status int, calls *int) string {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*calls++
		var got blueprint.Payload
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Errorf("decode payload: %v", err)
		}
		if want := blueprint.DefaultPayload(); got != want {
			t.Errorf("payload = %+v, want %+v", got, want)
		}
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"id":1}`))
	}))
	t.Cleanup(srv.Close)
	return srv.URL
}

func newMutator(t *testing.T, endpoint string, objs ...runtime.Object) *PodMutator {
	t.Helper()
	s := testScheme(t)
	builder := fake.NewClientBuilder().WithScheme(s)
	for _, o := range objs {
		builder = builder.WithRuntimeObjects(o)
	}
	return &PodMutator{
		Client:   builder.Build(),
		Decoder:  admission.NewDecoder(s),
		Notifier: blueprint.NewClient(endpoint, 2*time.Second, 2),
	}
}

func TestInjectsIdentityOnSuccess(t *testing.T) {
	calls := 0
	url := stubAPI(t, http.StatusCreated, &calls)
	m := newMutator(t, url, agentNamespace("agents", "true"))

	resp := m.Handle(context.Background(), request(t, agentPod()))

	if !resp.Allowed {
		t.Fatalf("expected pod to be allowed, got: %+v", resp.Result)
	}
	if calls != 1 {
		t.Fatalf("blueprint api called %d times, want 1", calls)
	}

	var sawEnvPatch bool
	for _, p := range resp.Patches {
		if p.Operation == "add" && p.Path == "/spec/containers/0/env" {
			sawEnvPatch = true
		}
	}
	if !sawEnvPatch {
		t.Fatalf("expected an env patch on container 0, got patches: %+v", resp.Patches)
	}
}

// This is the core guarantee: a failed API call must stop the pod from starting.
func TestDeniesPodWhenBlueprintAPIFails(t *testing.T) {
	calls := 0
	url := stubAPI(t, http.StatusInternalServerError, &calls)
	m := newMutator(t, url, agentNamespace("agents", "true"))

	resp := m.Handle(context.Background(), request(t, agentPod()))

	if resp.Allowed {
		t.Fatal("expected pod to be DENIED when the blueprint api call fails")
	}
	if calls != 2 {
		t.Fatalf("blueprint api called %d times, want 2 (retries exhausted)", calls)
	}
}

func TestSkipsNamespaceWithoutAgentEnabledLabel(t *testing.T) {
	calls := 0
	url := stubAPI(t, http.StatusCreated, &calls)
	m := newMutator(t, url, agentNamespace("agents", "false"))

	resp := m.Handle(context.Background(), request(t, agentPod()))

	if !resp.Allowed {
		t.Fatalf("expected pod to be allowed, got: %+v", resp.Result)
	}
	if calls != 0 {
		t.Fatalf("blueprint api called %d times, want 0 for out-of-scope namespace", calls)
	}
	if len(resp.Patches) != 0 {
		t.Fatalf("expected no patches, got: %+v", resp.Patches)
	}
}

func TestNonAgentPodIsUntouched(t *testing.T) {
	calls := 0
	url := stubAPI(t, http.StatusCreated, &calls)
	m := newMutator(t, url, agentNamespace("agents", "true"))

	pod := agentPod()
	pod.Annotations = nil

	resp := m.Handle(context.Background(), request(t, pod))

	if !resp.Allowed {
		t.Fatalf("expected pod to be allowed, got: %+v", resp.Result)
	}
	if calls != 0 {
		t.Fatalf("blueprint api called %d times, want 0 for a non-agent pod", calls)
	}
}

func TestSpoofedEnvValueIsOverwritten(t *testing.T) {
	calls := 0
	url := stubAPI(t, http.StatusCreated, &calls)
	m := newMutator(t, url, agentNamespace("agents", "true"))

	pod := agentPod()
	pod.Spec.Containers[0].Env = []corev1.EnvVar{
		{Name: agentid.EnvVarName, Value: "attacker-supplied"},
	}

	resp := m.Handle(context.Background(), request(t, pod))
	if !resp.Allowed {
		t.Fatalf("expected pod to be allowed, got: %+v", resp.Result)
	}

	var replaced bool
	for _, p := range resp.Patches {
		if p.Path == "/spec/containers/0/env/0/value" && p.Value == testGUID {
			replaced = true
		}
	}
	if !replaced {
		t.Fatalf("expected spoofed env value to be replaced with %q, patches: %+v", testGUID, resp.Patches)
	}
}

func TestDeniesMalformedBlueprintID(t *testing.T) {
	calls := 0
	url := stubAPI(t, http.StatusCreated, &calls)
	m := newMutator(t, url, agentNamespace("agents", "true"))

	pod := agentPod()
	pod.Annotations[agentid.AnnotationKey] = "12345"

	resp := m.Handle(context.Background(), request(t, pod))

	if resp.Allowed {
		t.Fatal("expected pod to be DENIED for a malformed blueprint id")
	}
	if calls != 0 {
		t.Fatalf("blueprint api called %d times, want 0 when validation fails first", calls)
	}
}
