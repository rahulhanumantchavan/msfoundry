from flask import Flask, request, jsonify
import uuid
import requests
import base64
import json

app = Flask(__name__)

@app.route('/mutate', methods=['POST'])
def mutate():
    req_data = request.get_json()
    
    # 1. Invoke REST API with dummy payload
    try:
        # Replace with your actual REST API endpoint
        requests.post("https://jsonplaceholder.typicode.com/posts", json={"userId": 1, "id": 1,"title": "title","body": "title"}, timeout=3)
    except Exception as e:
        print(f"API call failed: {e}. Proceeding anyway...")

    # 2. Generate random GUID
    new_guid = str(uuid.uuid4())

    # 3. Create JSON Patch to inject env var
    req = req_data.get('request', {})
    pod = req.get('object', {})
    
    patch = []
    containers = pod.get('spec', {}).get('containers', [])
    
    for i, container in enumerate(containers):
        new_env = {"name": "INJECTED_API_GUID", "value": new_guid}
        if 'env' not in container:
            # If the container has no env array yet, create it
            patch.append({"op": "add", "path": f"/spec/containers/{i}/env", "value": [new_env]})
        else:
            # If it does, append to it
            patch.append({"op": "add", "path": f"/spec/containers/{i}/env/-", "value": new_env})

    # Kubernetes requires the patch to be base64 encoded
    patch_b64 = base64.b64encode(json.dumps(patch).encode('utf-8')).decode('utf-8')

    # 4. Construct the AdmissionResponse
    admission_response = {
        "uid": req.get("uid"),
        "allowed": True,
        "patchType": "JSONPatch",
        "patch": patch_b64
    }

    return jsonify({
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": admission_response
    })

if __name__ == '__main__':
    # Webhooks MUST run over HTTPS. Certificates will be mounted via Kubernetes.
    app.run(host='0.0.0.0', port=8443, ssl_context=('/certs/tls.crt', '/certs/tls.key'))
