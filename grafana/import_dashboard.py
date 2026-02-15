# import_dashboard_fixed.py
import requests
import json
from pathlib import Path
import sys
from pathlib import Path
 

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


# Configuration
GRAFANA_URL = "http://localhost:3000"
GRAFANA_USER = "admin"
GRAFANA_PASS = "admin"
DASHBOARD_PATH = "dashboard.json"

def create_service_account_token():
    """Create a service account token (new way in Grafana 12+)"""
    print("Creating service account token...")
    
    # First, create a service account
    auth = (GRAFANA_USER, GRAFANA_PASS)
    
    # Create service account
    sa_payload = {
        "name": "dashboard-importer",
        "role": "Admin"
    }
    
    sa_response = requests.post(
        f"{GRAFANA_URL}/api/serviceaccounts",
        auth=auth,
        json=sa_payload
    )
    
    if sa_response.status_code != 200:
        print(f"Error creating service account: {sa_response.status_code}")
        print(sa_response.text)
        
        # Try to get existing service account
        list_response = requests.get(
            f"{GRAFANA_URL}/api/serviceaccounts/search",
            auth=auth
        )
        
        if list_response.status_code == 200:
            accounts = list_response.json().get('serviceAccounts', [])
            for acc in accounts:
                if acc['name'] == 'dashboard-importer':
                    sa_id = acc['id']
                    print(f"Found existing service account with ID: {sa_id}")
                    break
            else:
                return None
        else:
            return None
    else:
        sa_id = sa_response.json()['id']
        print(f"Created service account with ID: {sa_id}")
    
    # Create token for the service account
    token_payload = {
        "name": "import-token"
    }
    
    token_response = requests.post(
        f"{GRAFANA_URL}/api/serviceaccounts/{sa_id}/tokens",
        auth=auth,
        json=token_payload
    )
    
    if token_response.status_code == 200:
        token = token_response.json()['key']
        print("✅ Token created successfully")
        return token
    else:
        print(f"Error creating token: {token_response.status_code}")
        print(token_response.text)
        return None

def import_dashboard(token):
    """Import dashboard using token"""
    print(f"Loading dashboard from {DASHBOARD_PATH}...")
    
    # Read the dashboard file
    with open(DASHBOARD_PATH, 'r') as f:
        dashboard_json = json.load(f)
    
    # Prepare payload
    if 'dashboard' in dashboard_json:
        payload = dashboard_json
        payload['overwrite'] = True
    else:
        payload = {
            "dashboard": dashboard_json,
            "overwrite": True
        }
    
    # Import dashboard
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(
        f"{GRAFANA_URL}/api/dashboards/db",
        headers=headers,
        json=payload
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Dashboard imported successfully!")
        print(f"   URL: {GRAFANA_URL}{result.get('url', '')}")
        print(f"   Title: {result.get('title', 'Unknown')}")
        return True
    else:
        print(f"❌ Error importing dashboard: {response.status_code}")
        print(response.text)
        return False

def basic_auth_import():
    """Try simple basic auth import (easiest)"""
    print("Trying basic auth import...")
    
    with open(DASHBOARD_PATH, 'r') as f:
        dashboard_json = json.load(f)
    
    if 'dashboard' in dashboard_json:
        payload = dashboard_json
        payload['overwrite'] = True
    else:
        payload = {
            "dashboard": dashboard_json,
            "overwrite": True
        }
    
    response = requests.post(
        f"{GRAFANA_URL}/api/dashboards/db",
        auth=(GRAFANA_USER, GRAFANA_PASS),
        json=payload
    )
    
    if response.status_code == 200:
        print("✅ Dashboard imported with basic auth!")
        print(response.json())
        return True
    else:
        print(f"❌ Basic auth failed: {response.status_code}")
        print(response.text)
        return False

def main():
    print("=" * 60)
    print("Grafana Dashboard Importer")
    print("=" * 60)
    
    # Check if dashboard file exists
    if not Path(DASHBOARD_PATH).exists():
        print(f"❌ Dashboard file not found: {DASHBOARD_PATH}")
        print(f"   Make sure the file exists at: {Path(DASHBOARD_PATH).absolute()}")
        return False
    
    # Try basic auth first (simplest)
    if basic_auth_import():
        return True
    
    # If basic auth fails, try token method
    print("\nTrying token-based authentication...")
    token = create_service_account_token()
    if token:
        success = import_dashboard(token)
        if success:
            return True
    
    print("\n❌ All import methods failed.")
    print("\nLast resort: Import manually through UI:")
    print("1. Open http://localhost:3000")
    print("2. Login with admin/admin")
    print("3. Click + → Import")
    print("4. Upload your dashboard.json file")
    print("5. Select your data source")
    print("6. Click Import")
    
    return False

if __name__ == "__main__":
    main()