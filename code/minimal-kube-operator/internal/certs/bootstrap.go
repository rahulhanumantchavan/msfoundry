// Package certs generates the serving certificate for the admission webhook and
// publishes the CA bundle to the MutatingWebhookConfiguration.
//
// This keeps the deployment free of cert-manager. If cert-manager is preferred,
// set ENABLE_CERT_BOOTSTRAP=false and let it own the Secret instead.
package certs

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"time"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"sigs.k8s.io/controller-runtime/pkg/log"
)

// Options configures the bootstrap process.
type Options struct {
	Namespace       string
	ServiceName     string
	SecretName      string
	WebhookConfig   string
	CertDir         string
	ValidityInDays  int
}

// Ensure generates (or reuses) a serving certificate, writes it to CertDir and
// patches the MutatingWebhookConfiguration caBundle.
func Ensure(ctx context.Context, cfg *rest.Config, opts Options) error {
	logger := log.FromContext(ctx).WithName("certs")

	cs, err := kubernetes.NewForConfig(cfg)
	if err != nil {
		return fmt.Errorf("build kubernetes client: %w", err)
	}

	if opts.ValidityInDays <= 0 {
		opts.ValidityInDays = 3650
	}

	secret, err := cs.CoreV1().Secrets(opts.Namespace).Get(ctx, opts.SecretName, metav1.GetOptions{})
	exists := err == nil
	if err != nil && !apierrors.IsNotFound(err) {
		return fmt.Errorf("get secret %s/%s: %w", opts.Namespace, opts.SecretName, err)
	}

	var data map[string][]byte
	if exists && valid(secret.Data) {
		logger.Info("Reusing existing webhook serving certificate", "secret", opts.SecretName)
		data = secret.Data
	} else {
		logger.Info("Generating new self-signed webhook serving certificate")
		data, err = generate(opts)
		if err != nil {
			return err
		}

		if exists {
			secret.Data = data
			if _, err := cs.CoreV1().Secrets(opts.Namespace).Update(ctx, secret, metav1.UpdateOptions{}); err != nil {
				return fmt.Errorf("update secret %s/%s: %w", opts.Namespace, opts.SecretName, err)
			}
		} else {
			desired := &corev1.Secret{
				ObjectMeta: metav1.ObjectMeta{Name: opts.SecretName, Namespace: opts.Namespace},
				Type:       corev1.SecretTypeOpaque,
				Data:       data,
			}
			if _, err := cs.CoreV1().Secrets(opts.Namespace).Create(ctx, desired, metav1.CreateOptions{}); err != nil && !apierrors.IsAlreadyExists(err) {
				return fmt.Errorf("create secret %s/%s: %w", opts.Namespace, opts.SecretName, err)
			}
		}
	}

	if err := os.MkdirAll(opts.CertDir, 0o755); err != nil {
		return fmt.Errorf("create cert dir %s: %w", opts.CertDir, err)
	}
	for name, key := range map[string]string{"tls.crt": "tls.crt", "tls.key": "tls.key", "ca.crt": "ca.crt"} {
		if err := os.WriteFile(filepath.Join(opts.CertDir, name), data[key], 0o600); err != nil {
			return fmt.Errorf("write %s: %w", name, err)
		}
	}

	return patchWebhook(ctx, cs, opts, data["ca.crt"])
}

func valid(data map[string][]byte) bool {
	crt, ok := data["tls.crt"]
	if !ok || len(data["tls.key"]) == 0 || len(data["ca.crt"]) == 0 {
		return false
	}
	block, _ := pem.Decode(crt)
	if block == nil {
		return false
	}
	parsed, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return false
	}
	// Rotate a month before expiry.
	return time.Now().Add(30 * 24 * time.Hour).Before(parsed.NotAfter)
}

func generate(opts Options) (map[string][]byte, error) {
	notBefore := time.Now().Add(-time.Hour)
	notAfter := notBefore.AddDate(0, 0, opts.ValidityInDays)

	caKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return nil, fmt.Errorf("generate ca key: %w", err)
	}
	caTmpl := &x509.Certificate{
		SerialNumber:          serial(),
		Subject:               pkix.Name{CommonName: "agent-identity-operator-ca", Organization: []string{"contoso"}},
		NotBefore:             notBefore,
		NotAfter:              notAfter,
		IsCA:                  true,
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature | x509.KeyUsageCRLSign,
		BasicConstraintsValid: true,
	}
	caDER, err := x509.CreateCertificate(rand.Reader, caTmpl, caTmpl, &caKey.PublicKey, caKey)
	if err != nil {
		return nil, fmt.Errorf("create ca cert: %w", err)
	}
	caCert, err := x509.ParseCertificate(caDER)
	if err != nil {
		return nil, fmt.Errorf("parse ca cert: %w", err)
	}

	svcKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return nil, fmt.Errorf("generate serving key: %w", err)
	}
	dnsNames := []string{
		opts.ServiceName,
		fmt.Sprintf("%s.%s", opts.ServiceName, opts.Namespace),
		fmt.Sprintf("%s.%s.svc", opts.ServiceName, opts.Namespace),
		fmt.Sprintf("%s.%s.svc.cluster.local", opts.ServiceName, opts.Namespace),
	}
	svcTmpl := &x509.Certificate{
		SerialNumber: serial(),
		Subject:      pkix.Name{CommonName: dnsNames[2], Organization: []string{"contoso"}},
		DNSNames:     dnsNames,
		NotBefore:    notBefore,
		NotAfter:     notAfter,
		KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	svcDER, err := x509.CreateCertificate(rand.Reader, svcTmpl, caCert, &svcKey.PublicKey, caKey)
	if err != nil {
		return nil, fmt.Errorf("create serving cert: %w", err)
	}

	return map[string][]byte{
		"ca.crt":  pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: caDER}),
		"tls.crt": pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: svcDER}),
		"tls.key": pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(svcKey)}),
	}, nil
}

func serial() *big.Int {
	limit := new(big.Int).Lsh(big.NewInt(1), 128)
	n, err := rand.Int(rand.Reader, limit)
	if err != nil {
		return big.NewInt(time.Now().UnixNano())
	}
	return n
}

func patchWebhook(ctx context.Context, cs kubernetes.Interface, opts Options, caBundle []byte) error {
	logger := log.FromContext(ctx).WithName("certs")

	cfg, err := cs.AdmissionregistrationV1().MutatingWebhookConfigurations().
		Get(ctx, opts.WebhookConfig, metav1.GetOptions{})
	if err != nil {
		return fmt.Errorf("get mutatingwebhookconfiguration %s: %w", opts.WebhookConfig, err)
	}

	changed := false
	for i := range cfg.Webhooks {
		if string(cfg.Webhooks[i].ClientConfig.CABundle) != string(caBundle) {
			cfg.Webhooks[i].ClientConfig.CABundle = caBundle
			changed = true
		}
	}
	if !changed {
		logger.Info("Webhook caBundle already up to date", "webhookConfiguration", opts.WebhookConfig)
		return nil
	}

	if _, err := cs.AdmissionregistrationV1().MutatingWebhookConfigurations().
		Update(ctx, cfg, metav1.UpdateOptions{}); err != nil {
		return fmt.Errorf("update mutatingwebhookconfiguration %s: %w", opts.WebhookConfig, err)
	}
	logger.Info("Published caBundle to webhook configuration", "webhookConfiguration", opts.WebhookConfig)
	return nil
}
