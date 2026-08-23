// Package blueprint contains the client used by the operator to notify the
// external Agent Identity Blueprint API before an agent pod is admitted.
package blueprint

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"sigs.k8s.io/controller-runtime/pkg/log"
)

// DefaultEndpoint is the API contacted for every agent pod admission.
const DefaultEndpoint = "https://jsonplaceholder.typicode.com/posts"

// Payload is the request body sent to the blueprint API.
type Payload struct {
	UserID int    `json:"userId"`
	ID     int    `json:"id"`
	Title  string `json:"title"`
	Body   string `json:"body"`
}

// DefaultPayload is the fixed payload mandated by the integration contract.
func DefaultPayload() Payload {
	return Payload{UserID: 1, ID: 1, Title: "title", Body: "title"}
}

// Client calls the Agent Identity Blueprint API.
type Client struct {
	Endpoint   string
	HTTPClient *http.Client
	// MaxAttempts is the total number of attempts (1 == no retry).
	MaxAttempts int
	// RetryBackoff is the delay between attempts.
	RetryBackoff time.Duration
}

// NewClient builds a Client with sane defaults.
func NewClient(endpoint string, timeout time.Duration, maxAttempts int) *Client {
	if endpoint == "" {
		endpoint = DefaultEndpoint
	}
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	if maxAttempts <= 0 {
		maxAttempts = 3
	}
	return &Client{
		Endpoint:     endpoint,
		HTTPClient:   &http.Client{Timeout: timeout},
		MaxAttempts:  maxAttempts,
		RetryBackoff: 500 * time.Millisecond,
	}
}

// Notify posts the fixed payload to the blueprint API.
//
// The call is logged as success or failure. An error is returned when every
// attempt failed, which causes the admission request to be denied so that the
// pod never starts.
func (c *Client) Notify(ctx context.Context, blueprintID, namespace, workload string) error {
	logger := log.FromContext(ctx).WithValues(
		"endpoint", c.Endpoint,
		"agentBlueprintId", blueprintID,
		"namespace", namespace,
		"workload", workload,
	)

	body, err := json.Marshal(DefaultPayload())
	if err != nil {
		return fmt.Errorf("marshal blueprint payload: %w", err)
	}

	var lastErr error
	for attempt := 1; attempt <= c.MaxAttempts; attempt++ {
		status, respBody, err := c.do(ctx, body)
		if err == nil && status >= 200 && status < 300 {
			logger.Info("Agent Identity Blueprint API call SUCCESS",
				"attempt", attempt, "httpStatus", status, "response", truncate(respBody, 256))
			return nil
		}

		if err != nil {
			lastErr = err
		} else {
			lastErr = fmt.Errorf("unexpected http status %d: %s", status, truncate(respBody, 256))
		}
		logger.Error(lastErr, "Agent Identity Blueprint API call FAILED", "attempt", attempt)

		if attempt < c.MaxAttempts {
			select {
			case <-ctx.Done():
				return fmt.Errorf("blueprint api call aborted: %w", ctx.Err())
			case <-time.After(c.RetryBackoff * time.Duration(attempt)):
			}
		}
	}

	return fmt.Errorf("blueprint api call failed after %d attempt(s): %w", c.MaxAttempts, lastErr)
}

func (c *Client) do(ctx context.Context, body []byte) (int, string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Endpoint, bytes.NewReader(body))
	if err != nil {
		return 0, "", fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json; charset=UTF-8")
	req.Header.Set("Accept", "application/json")

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return 0, "", fmt.Errorf("execute request: %w", err)
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
	if err != nil {
		return resp.StatusCode, "", fmt.Errorf("read response: %w", err)
	}
	return resp.StatusCode, string(raw), nil
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}
