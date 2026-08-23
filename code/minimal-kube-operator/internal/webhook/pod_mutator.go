// Package webhook implements the mutating admission webhook that gates agent
// pod creation.
package webhook

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sort"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	admission "sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	"github.com/contoso/agent-identity-operator/internal/agentid"
	"github.com/contoso/agent-identity-operator/internal/blueprint"
)

// PodMutator injects the Agent Identity Blueprint ID into agent pods after a
// successful call to the blueprint API.
//
// Because this runs as a *failurePolicy: Fail* mutating webhook on pod CREATE,
// the pod object is never persisted — and therefore never scheduled or started —
// unless every step below succeeds.
type PodMutator struct {
	Client   client.Reader
	Decoder  admission.Decoder
	Notifier *blueprint.Client

	// EnforceNamespaceServiceAccount pins agent pods to the single pre-existing
	// namespace service account when the pod did not request one explicitly.
	EnforceNamespaceServiceAccount bool
}

// Handle implements admission.Handler.
func (m *PodMutator) Handle(ctx context.Context, req admission.Request) admission.Response {
	logger := logf.FromContext(ctx).WithValues(
		"namespace", req.Namespace,
		"pod", podName(req),
		"uid", string(req.UID),
	)
	ctx = logf.IntoContext(ctx, logger)

	pod := &corev1.Pod{}
	if err := m.Decoder.Decode(req, pod); err != nil {
		logger.Error(err, "Failed to decode pod from admission request")
		return admission.Errored(http.StatusBadRequest, err)
	}

	// Defence in depth: the webhook configuration already restricts traffic with
	// a namespaceSelector, but never trust the caller.
	inScope, err := m.namespaceInScope(ctx, req.Namespace)
	if err != nil {
		logger.Error(err, "Failed to read namespace labels")
		return admission.Errored(http.StatusInternalServerError, err)
	}
	if !inScope {
		return admission.Allowed(fmt.Sprintf(
			"namespace %q is not labelled %s=%s; skipping",
			req.Namespace, agentid.NamespaceLabelKey, agentid.NamespaceLabelValue))
	}

	result, err := agentid.Resolve(ctx, m.Client, pod, req.Namespace)
	if err != nil {
		// A malformed or unreadable blueprint reference must block the pod.
		logger.Error(err, "Failed to resolve Agent Identity Blueprint ID")
		return admission.Denied(fmt.Sprintf("agent identity blueprint resolution failed: %v", err))
	}
	if result.ID == "" {
		return admission.Allowed(fmt.Sprintf(
			"no %s annotation found; workload is not an agent", agentid.AnnotationKey))
	}

	logger = logger.WithValues("agentBlueprintId", result.ID, "source", result.Source)
	ctx = logf.IntoContext(ctx, logger)

	// Step 1 — call the external blueprint API and log the outcome.
	if err := m.Notifier.Notify(ctx, result.ID, req.Namespace, result.Source); err != nil {
		logger.Error(err, "Denying pod admission because the blueprint API call failed")
		return admission.Denied(fmt.Sprintf("agent identity blueprint api call failed: %v", err))
	}

	// Step 2 — inject AGENT_IDENTITY_ID into every container.
	mutated := pod.DeepCopy()
	injected := injectEnv(mutated, result.ID)

	// Step 3 — optionally pin the pod to the namespace's agent service account.
	if m.EnforceNamespaceServiceAccount && mutated.Spec.ServiceAccountName == "" {
		sa, err := m.namespaceServiceAccount(ctx, req.Namespace)
		if err != nil {
			logger.Error(err, "Failed to resolve namespace service account")
			return admission.Denied(fmt.Sprintf("service account resolution failed: %v", err))
		}
		if sa != "" {
			mutated.Spec.ServiceAccountName = sa
			logger.Info("Pinned pod to namespace agent service account", "serviceAccountName", sa)
		}
	}

	// Step 4 — stamp provenance so the mutation is auditable.
	if mutated.Annotations == nil {
		mutated.Annotations = map[string]string{}
	}
	mutated.Annotations[agentid.AnnotationKey] = result.ID
	mutated.Annotations[agentid.InjectedAnnotation] = "true"
	mutated.Annotations[agentid.SourceAnnotation] = result.Source

	patched, err := json.Marshal(mutated)
	if err != nil {
		logger.Error(err, "Failed to marshal mutated pod")
		return admission.Errored(http.StatusInternalServerError, err)
	}

	logger.Info("Admitting agent pod with injected identity",
		"envVar", agentid.EnvVarName, "containersPatched", injected)

	return admission.PatchResponseFromRaw(req.Object.Raw, patched)
}

func (m *PodMutator) namespaceInScope(ctx context.Context, name string) (bool, error) {
	ns := &corev1.Namespace{}
	if err := m.Client.Get(ctx, types.NamespacedName{Name: name}, ns); err != nil {
		return false, err
	}
	return ns.Labels[agentid.NamespaceLabelKey] == agentid.NamespaceLabelValue, nil
}

// namespaceServiceAccount returns the single non-default service account in the
// namespace. It returns an error when the assumption of exactly one is violated.
func (m *PodMutator) namespaceServiceAccount(ctx context.Context, namespace string) (string, error) {
	list := &corev1.ServiceAccountList{}
	if err := m.Client.List(ctx, list, client.InNamespace(namespace)); err != nil {
		return "", fmt.Errorf("list service accounts in %s: %w", namespace, err)
	}

	var names []string
	for _, sa := range list.Items {
		if sa.Name == "default" {
			continue
		}
		names = append(names, sa.Name)
	}
	sort.Strings(names)

	switch len(names) {
	case 0:
		return "", nil
	case 1:
		return names[0], nil
	default:
		return "", fmt.Errorf(
			"expected exactly one agent service account in namespace %s, found %d: %v",
			namespace, len(names), names)
	}
}

// injectEnv sets AGENT_IDENTITY_ID on every init and app container, replacing
// any pre-existing value so a caller cannot spoof the identity.
func injectEnv(pod *corev1.Pod, id string) int {
	count := 0
	for i := range pod.Spec.InitContainers {
		setEnv(&pod.Spec.InitContainers[i], id)
		count++
	}
	for i := range pod.Spec.Containers {
		setEnv(&pod.Spec.Containers[i], id)
		count++
	}
	return count
}

func setEnv(c *corev1.Container, id string) {
	for i := range c.Env {
		if c.Env[i].Name == agentid.EnvVarName {
			c.Env[i].Value = id
			c.Env[i].ValueFrom = nil
			return
		}
	}
	c.Env = append(c.Env, corev1.EnvVar{Name: agentid.EnvVarName, Value: id})
}

func podName(req admission.Request) string {
	if req.Name != "" {
		return req.Name
	}
	return "<generated>"
}
