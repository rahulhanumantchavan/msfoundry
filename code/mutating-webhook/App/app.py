from flask import Flask, request, jsonify
import uuid
import requests
import base64
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s'
)

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
logger = logging.getLogger("kube-operator")
logger.setLevel(logging.INFO)


@app.route('/mutate', methods=['POST'])
def mutate():
    logger.info("Admission webhook /mutate invoked")
    logger.info("Request method=%s headers=%s", request.method, dict(request.headers))

    try:
        req_data = request.get_json(silent=False)
        logger.info("Incoming AdmissionReview payload: %s", json.dumps(req_data, default=str)[:4000])
    except Exception as exc:
        logger.exception("Failed to parse JSON payload from admission webhook: %s", exc)
        return jsonify({
            "apiVersion": "admission.k8s.io/v1",
            "kind": "AdmissionReview",
            "response": {
                "uid": "",
                "allowed": False,
                "status": {
                    "code": 400,
                    "message": "Invalid JSON request body"
                }
            }
        }), 400

    if not isinstance(req_data, dict):
        logger.warning("Request JSON is not an object: %r", type(req_data))
        return jsonify({
            "apiVersion": "admission.k8s.io/v1",
            "kind": "AdmissionReview",
            "response": {
                "uid": "",
                "allowed": False,
                "status": {
                    "code": 400,
                    "message": "AdmissionReview payload must be a JSON object"
                }
            }
        }), 400

    req = req_data.get('request', {})
    pod = req.get('object', {})
    metadata = pod.get('metadata', {})
    pod_spec = pod.get('spec', {})
    containers = pod_spec.get('containers', [])

    logger.info(
        "Admission details: uid=%s namespace=%s kind=%s name=%s",
        req.get('uid'),
        metadata.get('namespace'),
        pod.get('kind'),
        metadata.get('name')
    )
    logger.info("Container count found in pod: %s", len(containers))

    # 1. Invoke REST API with dummy payload
    try:
        api_url = "https://jsonplaceholder.typicode.com/posts"
        api_payload = {"userId": 1, "id": 1, "title": "title", "body": "title"}
        logger.info("Calling external API: url=%s payload=%s", api_url, api_payload)
        api_response = requests.post(api_url, json=api_payload, timeout=3)
        logger.info(
            "External API response: status_code=%s headers=%s body=%s",
            api_response.status_code,
            dict(api_response.headers),
            api_response.text[:1000]
        )
    except Exception as exc:
        logger.exception("API call failed: %s. Proceeding anyway...", exc)

    # 2. Generate random GUID
    new_guid = str(uuid.uuid4())
    logger.info("Generated injected GUID: %s", new_guid)

    # 3. Create JSON Patch to inject env var
    patch = []
    for i, container in enumerate(containers):
        container_name = container.get('name', f'container-{i}')
        logger.info("Processing container[%s] name=%s", i, container_name)

        new_env = {"name": "INJECTED_API_GUID", "value": new_guid}
        if 'env' not in container:
            logger.info("Container %s has no env array. Adding env list with injected value.", container_name)
            patch.append({"op": "add", "path": f"/spec/containers/{i}/env", "value": [new_env]})
        else:
            logger.info("Container %s already has env entries. Appending injected value.", container_name)
            patch.append({"op": "add", "path": f"/spec/containers/{i}/env/-", "value": new_env})

    logger.info("Generated JSON patch before encoding: %s", json.dumps(patch, default=str))

    # Kubernetes requires the patch to be base64 encoded
    patch_b64 = base64.b64encode(json.dumps(patch).encode('utf-8')).decode('utf-8')
    logger.info("Base64-encoded patch length: %s", len(patch_b64))

    # 4. Construct the AdmissionResponse
    admission_response = {
        "uid": req.get("uid"),
        "allowed": True,
        "patchType": "JSONPatch",
        "patch": patch_b64
    }

    response_body = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": admission_response
    }

    logger.info("Sending AdmissionReview response: %s", json.dumps(response_body, default=str))
    return jsonify(response_body)


if __name__ == '__main__':
    # Webhooks MUST run over HTTPS. Certificates will be mounted via Kubernetes.
    logger.info("Starting webhook server on 0.0.0.0:8443 with TLS enabled")
    app.run(host='0.0.0.0', port=8443, ssl_context=('/certs/tls.crt', '/certs/tls.key'))
