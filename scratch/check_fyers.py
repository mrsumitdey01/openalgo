import os
import sys

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.auth_db import get_auth
from broker.fyers.fyers_api import FyersAPI

auth_data = get_auth("fyers", None)
if not auth_data:
    print("Fyers auth not found")
    exit(1)

api = FyersAPI()
api.setup(auth_data)

print("Fyers API initialized:", api)
