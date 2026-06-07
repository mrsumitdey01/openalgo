import requests
import re

url = "https://public.fyers.in/sym_details/MCX_COM.csv"
response = requests.get(url)

if response.status_code == 200:
    for line in response.text.split("\n"):
        if "GOLDM" in line and ("1!" in line or "-I" in line or "-II" in line):
            print(line)
        elif "GOLDM" in line and "FUT" in line:
            parts = line.split(',')
            if len(parts) > 13:
                print(parts[13], parts[9])
else:
    print("Failed to download")
