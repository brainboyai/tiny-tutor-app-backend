import base64
import json
import os

    # Path to your downloaded Firebase service account JSON file
SERVICE_ACCOUNT_FILE = "firebase-service-account.json"

try:
        with open(SERVICE_ACCOUNT_FILE, 'r') as f:
            # Load the JSON content. json.dumps will ensure it's a single line
            # and properly escape any internal newlines or special characters.
            service_account_data = json.load(f)
            service_account_json_string = json.dumps(service_account_data)

        # Encode the JSON string to Base64
        base64_encoded_string = base64.b64encode(service_account_json_string.encode('utf-8')).decode('utf-8')

        print("--- COPY THIS ENTIRE STRING ---")
        print(base64_encoded_string)
        print("--- END COPY ---")

except FileNotFoundError:
        print(f"Error: {SERVICE_ACCOUNT_FILE} not found. Make sure it's in the same directory.")
except json.JSONDecodeError as e:
        print(f"Error: Could not decode JSON from {SERVICE_ACCOUNT_FILE}. Check file integrity. Error: {e}")
except Exception as e:
        print(f"An unexpected error occurred: {e}")

    