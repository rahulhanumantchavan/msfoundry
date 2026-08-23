// Command operator runs the Agent Identity Blueprint operator.
//
// It exposes a mutating admission webhook on pod CREATE which, for namespaces
// labelled agent-enabled=true:
//
//	1. resolves the agent.blueprint/id annotation from the pod's Deployment,
//	2. calls the Agent Identity Blueprint API and logs the outcome,
//	3. injects AGENT_IDENTITY_ID into every container,
//	4. denies admission if any step fails, so the pod never starts.
package main

import (
	"flag"
	"os"
	"strconv"
	"time"

	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
	ctrlwebhook "sigs.k8s.io/controller-runtime/pkg/webhook"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	"github.com/contoso/agent-identity-operator/internal/agentid"
	"github.com/contoso/agent-identity-operator/internal/blueprint"
	"github.com/contoso/agent-identity-operator/internal/certs"
	agentwebhook "github.com/contoso/agent-identity-operator/internal/webhook"
)

var (
	scheme   = runtime.NewScheme()
	setupLog = ctrl.Log.WithName("setup")
)

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
}

func main() {
	var (
		metricsAddr    string
		probeAddr      string
		webhookPort    int
		certDir        string
		blueprintURL   string
		requestTimeout time.Duration
		maxAttempts    int
	)

	flag.StringVar(&metricsAddr, "metrics-bind-address", ":8080", "Address the metric endpoint binds to.")
	flag.StringVar(&probeAddr, "health-probe-bind-address", ":8081", "Address the probe endpoint binds to.")
	flag.IntVar(&webhookPort, "webhook-port", 9443, "Port the admission webhook server binds to.")
	flag.StringVar(&certDir, "cert-dir", "/tmp/k8s-webhook-server/serving-certs", "Directory holding tls.crt and tls.key.")
	flag.StringVar(&blueprintURL, "blueprint-api-url", envOr("BLUEPRINT_API_URL", blueprint.DefaultEndpoint), "Agent Identity Blueprint API endpoint.")
	flag.DurationVar(&requestTimeout, "blueprint-api-timeout", envDuration("BLUEPRINT_API_TIMEOUT", 5*time.Second), "Per-attempt timeout for the blueprint API call.")
	flag.IntVar(&maxAttempts, "blueprint-api-attempts", envInt("BLUEPRINT_API_ATTEMPTS", 3), "Total attempts for the blueprint API call.")

	opts := zap.Options{Development: envBool("DEV_LOGGING", false)}
	opts.BindFlags(flag.CommandLine)
	flag.Parse()

	ctrl.SetLogger(zap.New(zap.UseFlagOptions(&opts)))

	cfg := ctrl.GetConfigOrDie()
	namespace := envOr("POD_NAMESPACE", "agent-operator-system")
	ctx := ctrl.SetupSignalHandler()

	// Generate serving certs and publish the caBundle before the server starts.
	if envBool("ENABLE_CERT_BOOTSTRAP", true) {
		if err := certs.Ensure(ctx, cfg, certs.Options{
			Namespace:     namespace,
			ServiceName:   envOr("WEBHOOK_SERVICE_NAME", "agent-identity-operator-webhook"),
			SecretName:    envOr("WEBHOOK_SECRET_NAME", "agent-identity-operator-webhook-cert"),
			WebhookConfig: envOr("WEBHOOK_CONFIG_NAME", "agent-identity-operator-mutating-webhook"),
			CertDir:       certDir,
		}); err != nil {
			setupLog.Error(err, "Unable to bootstrap webhook certificates")
			os.Exit(1)
		}
	}

	mgr, err := ctrl.NewManager(cfg, ctrl.Options{
		Scheme:                 scheme,
		Metrics:                metricsserver.Options{BindAddress: metricsAddr},
		HealthProbeBindAddress: probeAddr,
		WebhookServer: ctrlwebhook.NewServer(ctrlwebhook.Options{
			Port:    webhookPort,
			CertDir: certDir,
		}),
	})
	if err != nil {
		setupLog.Error(err, "Unable to start manager")
		os.Exit(1)
	}

	notifier := blueprint.NewClient(blueprintURL, requestTimeout, maxAttempts)

	mgr.GetWebhookServer().Register("/mutate-v1-pod", &admission.Webhook{
		Handler: &agentwebhook.PodMutator{
			Client:                         mgr.GetClient(),
			Decoder:                        admission.NewDecoder(scheme),
			Notifier:                       notifier,
			EnforceNamespaceServiceAccount: envBool("ENFORCE_NAMESPACE_SERVICE_ACCOUNT", true),
		},
	})

	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		setupLog.Error(err, "Unable to set up health check")
		os.Exit(1)
	}
	if err := mgr.AddReadyzCheck("readyz", mgr.GetWebhookServer().StartedChecker()); err != nil {
		setupLog.Error(err, "Unable to set up ready check")
		os.Exit(1)
	}

	setupLog.Info("Starting agent identity operator",
		"blueprintApi", blueprintURL,
		"namespaceSelector", agentid.NamespaceLabelKey+"="+agentid.NamespaceLabelValue,
		"envVar", agentid.EnvVarName)

	if err := mgr.Start(ctx); err != nil {
		setupLog.Error(err, "Manager exited with error")
		os.Exit(1)
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envBool(key string, fallback bool) bool {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(v)
	if err != nil {
		return fallback
	}
	return parsed
}

func envInt(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(v)
	if err != nil {
		return fallback
	}
	return parsed
}

func envDuration(key string, fallback time.Duration) time.Duration {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	parsed, err := time.ParseDuration(v)
	if err != nil {
		return fallback
	}
	return parsed
}
