from google_auth_oauthlib.flow import InstalledAppFlow
import pickle, os

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",  # needed for CRM email scanning
]

flow = InstalledAppFlow.from_client_secrets_file("config/google_credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

with open("config/google_token.pickle", "wb") as f:
    pickle.dump(creds, f)
print("✅ Google auth saved to config/google_token.pickle")
