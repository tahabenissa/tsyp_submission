import os
import requests
from dotenv import load_dotenv

load_dotenv()  

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)

resp = requests.post(
    TOKEN_URL,
    data={
        "grant_type": "client_credentials",
        "client_id": os.environ["CDSE_CLIENT_ID"],
        "client_secret": os.environ["CDSE_CLIENT_SECRET"],
    },
    timeout=30,
)

if resp.status_code == 200:
    print("OK: access token received")
else:
    print("FAILED:", resp.status_code)