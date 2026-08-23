// Package agentid resolves the Agent Identity Blueprint ID for an agent pod.
package agentid

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

const (
	// AnnotationKey is the annotation carrying the Agent Identity Blueprint ID.
	AnnotationKey = "agent.blueprint/id"

	// EnvVarName is the environment variable injected into every agent container.
	EnvVarName = "AGENT_IDENTITY_ID"

	// InjectedAnnotation records that the operator has completed its work.
	InjectedAnnotation = "agent.blueprint/injected"

	// SourceAnnotation records where the blueprint ID was resolved from.
	SourceAnnotation = "agent.blueprint/source"

	// NamespaceLabelKey / NamespaceLabelValue gate which namespaces are in scope.
	NamespaceLabelKey   = "agent-enabled"
	NamespaceLabelValue = "true"
)

// guidPattern validates the canonical 8-4-4-4-12 GUID form.
var guidPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

// Result describes a resolved blueprint ID and its origin.
type Result struct {
	ID     string
	Source string
}

// Resolve walks the pod's ownership chain to find the Agent Identity Blueprint ID.
//
// Kubernetes does not copy a Deployment's own metadata.annotations onto the pods
// it creates, so the lookup order is:
//
//	1. the pod's own annotations (covers spec.template.metadata.annotations)
//	2. the owning ReplicaSet's annotations
//	3. the owning Deployment's annotations
//
// An empty Result with no error means the workload is not an agent.
func Resolve(ctx context.Context, c client.Reader, pod *corev1.Pod, namespace string) (Result, error) {
	if id, ok := lookup(pod.Annotations); ok {
		return validated(id, "pod")
	}

	rsName, ok := ownerOfKind(pod.OwnerReferences, "ReplicaSet")
	if !ok {
		return Result{}, nil
	}

	rs := &appsv1.ReplicaSet{}
	if err := c.Get(ctx, types.NamespacedName{Namespace: namespace, Name: rsName}, rs); err != nil {
		return Result{}, fmt.Errorf("get replicaset %s/%s: %w", namespace, rsName, err)
	}
	if id, ok := lookup(rs.Annotations); ok {
		return validated(id, "replicaset/"+rsName)
	}
	if id, ok := lookup(rs.Spec.Template.Annotations); ok {
		return validated(id, "replicaset/"+rsName+"#template")
	}

	deployName, ok := ownerOfKind(rs.OwnerReferences, "Deployment")
	if !ok {
		return Result{}, nil
	}

	deploy := &appsv1.Deployment{}
	if err := c.Get(ctx, types.NamespacedName{Namespace: namespace, Name: deployName}, deploy); err != nil {
		return Result{}, fmt.Errorf("get deployment %s/%s: %w", namespace, deployName, err)
	}
	if id, ok := lookup(deploy.Annotations); ok {
		return validated(id, "deployment/"+deployName)
	}
	if id, ok := lookup(deploy.Spec.Template.Annotations); ok {
		return validated(id, "deployment/"+deployName+"#template")
	}

	return Result{}, nil
}

func lookup(annotations map[string]string) (string, bool) {
	if annotations == nil {
		return "", false
	}
	v := strings.TrimSpace(annotations[AnnotationKey])
	if v == "" {
		return "", false
	}
	return v, true
}

func validated(id, source string) (Result, error) {
	if !guidPattern.MatchString(id) {
		return Result{}, fmt.Errorf(
			"annotation %q value %q (from %s) is not a valid GUID", AnnotationKey, id, source)
	}
	return Result{ID: strings.ToLower(id), Source: source}, nil
}

func ownerOfKind(refs []metav1.OwnerReference, kind string) (string, bool) {
	for _, ref := range refs {
		if ref.Kind == kind && strings.HasPrefix(ref.APIVersion, "apps/") {
			return ref.Name, true
		}
	}
	return "", false
}
