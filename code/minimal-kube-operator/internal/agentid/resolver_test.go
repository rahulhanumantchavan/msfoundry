package agentid

import (
	"context"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

const testGUID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

func newScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	s := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(s); err != nil {
		t.Fatalf("add scheme: %v", err)
	}
	return s
}

func podOwnedBy(rsName string, annotations map[string]string) *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:        "agent-pod",
			Namespace:   "agents",
			Annotations: annotations,
			OwnerReferences: []metav1.OwnerReference{{
				APIVersion: "apps/v1",
				Kind:       "ReplicaSet",
				Name:       rsName,
			}},
		},
	}
}

func TestResolveFromPodAnnotation(t *testing.T) {
	c := fake.NewClientBuilder().WithScheme(newScheme(t)).Build()
	pod := podOwnedBy("rs", map[string]string{AnnotationKey: testGUID})

	got, err := Resolve(context.Background(), c, pod, "agents")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.ID != testGUID {
		t.Fatalf("got id %q, want %q", got.ID, testGUID)
	}
	if got.Source != "pod" {
		t.Fatalf("got source %q, want %q", got.Source, "pod")
	}
}

func TestResolveWalksToDeployment(t *testing.T) {
	rs := &appsv1.ReplicaSet{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "rs",
			Namespace: "agents",
			OwnerReferences: []metav1.OwnerReference{{
				APIVersion: "apps/v1",
				Kind:       "Deployment",
				Name:       "deploy",
			}},
		},
	}
	deploy := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:        "deploy",
			Namespace:   "agents",
			Annotations: map[string]string{AnnotationKey: testGUID},
		},
	}

	c := fake.NewClientBuilder().WithScheme(newScheme(t)).WithObjects(rs, deploy).Build()

	got, err := Resolve(context.Background(), c, podOwnedBy("rs", nil), "agents")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.ID != testGUID {
		t.Fatalf("got id %q, want %q", got.ID, testGUID)
	}
	if got.Source != "deployment/deploy" {
		t.Fatalf("got source %q, want %q", got.Source, "deployment/deploy")
	}
}

func TestResolveNoAnnotationIsNotAnAgent(t *testing.T) {
	rs := &appsv1.ReplicaSet{
		ObjectMeta: metav1.ObjectMeta{Name: "rs", Namespace: "agents"},
	}
	c := fake.NewClientBuilder().WithScheme(newScheme(t)).WithObjects(rs).Build()

	got, err := Resolve(context.Background(), c, podOwnedBy("rs", nil), "agents")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.ID != "" {
		t.Fatalf("expected empty id, got %q", got.ID)
	}
}

func TestResolveRejectsMalformedGUID(t *testing.T) {
	c := fake.NewClientBuilder().WithScheme(newScheme(t)).Build()
	pod := podOwnedBy("rs", map[string]string{AnnotationKey: "not-a-guid"})

	if _, err := Resolve(context.Background(), c, pod, "agents"); err == nil {
		t.Fatal("expected an error for a malformed GUID, got nil")
	}
}
