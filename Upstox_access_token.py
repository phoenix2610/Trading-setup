import requests
import re
import json
import os
import pyotp
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta
from collections import defaultdict



API_KEY = "ENTER YOUR API KEY"
SECRET_API="ENTER YOUR SECRET"
TOTP_SECRET="NOT NECESSARY"
rurl="Redirected URL"  # basically the local hosted version which you used while filling up the API 


CRED_FILE = "upstox_cred.py"
NSE_JSON_PATH = r"nse_main.json"

def get_nearest_nifty_expiry_from_json():
    """
    Parse NSE_main.json to find the nearest NIFTY expiry date
    """
    try:
        if not os.path.exists(NSE_JSON_PATH):
            print(f"⚠️  NSE_main.json not found at {NSE_JSON_PATH}")
            return get_nearest_thursday_fallback()
        
        with open(NSE_JSON_PATH, 'r') as f:
            instruments = json.load(f)
        
        today = datetime.now().date()
        nifty_expiries = set()
        
        # Parse through instruments to find NIFTY options
        for instrument in instruments:
            # Check if it's a NIFTY option (CE or PE)
            if isinstance(instrument, dict):
                name = instrument.get('name', '').upper()
                instrument_type = instrument.get('instrument_type', '').upper()
                
                # Look for NIFTY options
                if 'NIFTY' in name and instrument_type in ['CE', 'PE']:
                    expiry_str = instrument.get('expiry')
                    if expiry_str:
                        try:
                            # Parse expiry date (format might be YYYY-MM-DD or timestamp)
                            if isinstance(expiry_str, str):
                                expiry_date = datetime.strptime(expiry_str.split('T')[0], '%Y-%m-%d').date()
                            elif isinstance(expiry_str, int):
                                # If it's a timestamp in milliseconds
                                expiry_date = datetime.fromtimestamp(expiry_str / 1000).date()
                            else:
                                continue
                            
                            # Only consider future expiries
                            if expiry_date >= today:
                                nifty_expiries.add(expiry_date)
                        except (ValueError, TypeError):
                            continue
        
        if nifty_expiries:
            nearest_expiry = min(nifty_expiries)
            print(f"✅ Found nearest NIFTY expiry from NSE_main.json: {nearest_expiry}")
            return datetime.combine(nearest_expiry, datetime.min.time())
        else:
            print("⚠️  No future NIFTY expiries found in JSON, using Thursday fallback")
            return get_nearest_thursday_fallback()
            
    except Exception as e:
        print(f"⚠️  Error parsing NSE_main.json: {e}")
        print("Using Thursday fallback method")
        return get_nearest_thursday_fallback()

def get_nearest_thursday_fallback():
    """
    Fallback: Calculate the nearest Thursday for options expiry
    """
    today = datetime.now()
    current_weekday = today.weekday()  # Monday=0, Sunday=6
    
    # Thursday is weekday 3
    if current_weekday < 3:  # Monday, Tuesday, Wednesday
        days_until_thursday = 3 - current_weekday
        return today + timedelta(days=days_until_thursday)
    elif current_weekday == 3:  # Thursday
        return today  # Same day if it's Thursday
    elif current_weekday == 4:  # Friday
        # Next Thursday (6 days later)
        return today + timedelta(days=6)
    else:  # Saturday, Sunday
        # Next Thursday
        days_until_thursday = (3 - current_weekday) % 7
        return today + timedelta(days=days_until_thursday)

def get_auth_code_with_otp():
    """Get auth code using TOTP without browser interaction"""
    try:
        # Generate OTP directly using pyotp
        totp = pyotp.TOTP(TOTP_SECRET)
        otp_code = totp.now()
        print(f"\n🔐 Generated OTP: {otp_code}")
        
        # Login URL
        url = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={API_KEY}&redirect_uri={rurl}"
        print(f"\n🔗 Login URL: {url}")
        print(f"💡 Use OTP: {otp_code}")
        print("\n📋 Steps:")
        print("   1. Open the URL above in your browser")
        print("   2. Enter your credentials and the OTP shown above")
        print("   3. After login, copy the FULL redirect URL from browser")
        
        redirect = input("\n📌 Paste the full redirect URL here: ").strip()
        parsed = urlparse(redirect)
        code = parse_qs(parsed.query).get("code", [None])[0]
        if not code:
            raise ValueError("Auth code not found in URL.")
        return code
    except Exception as e:
        print(f"❌ OTP generation failed: {e}")
        # Fallback to original method
        return get_auth_code_manual()

def get_auth_code_manual():
    """Fallback manual auth code method"""
    import webbrowser
    url = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={API_KEY}&redirect_uri={rurl}"
    webbrowser.open(url)
    redirect = input("\n📌 Paste the full redirect URL after login: ").strip()
    parsed = urlparse(redirect)
    code = parse_qs(parsed.query).get("code", [None])[0]
    if not code:
        raise ValueError("Auth code not found in URL.")
    return code

def get_access_token(auth_code):
    """Exchange auth code for access token"""
    url = "https://api.upstox.com/v2/login/authorization/token"
    payload = {
        "code": auth_code,
        "client_id": API_KEY,
        "client_secret": SECRET_API,
        "redirect_uri": rurl,
        "grant_type": "authorization_code"
    }
    res = requests.post(url, data=payload)
    res.raise_for_status()
    data = res.json()
    
    # Get nearest expiry from JSON
    expiry_date = get_nearest_nifty_expiry_from_json()
    return data["access_token"], expiry_date

def update_cred_file(token, expiry_date):
    """Update credential file with new token and expiry"""
    with open(CRED_FILE, "r") as f:
        content = f.read()

    content = re.sub(r'ACCESS_TOKEN\s*=\s*".*?"', f'ACCESS_TOKEN = "{token}"', content)
    content = re.sub(r'EXPIRY_DATE\s*=\s*".*?"', f'EXPIRY_DATE = "{expiry_date.strftime("%Y-%m-%d")}"', content)

    with open(CRED_FILE, "w") as f:
        f.write(content)

    print(f"\n✅ Token updated successfully!")
    print(f"📅 Expiry Date: {expiry_date.strftime('%Y-%m-%d')} ({expiry_date.strftime('%A')})")

def main():
    print("=" * 60)
    print("🔄 Upstox Token & Expiry Updater")
    print("=" * 60)
    
    try:
        # Step 1: Get auth code
        print("\n📡 Step 1: Getting authorization code...")
        auth_code = get_auth_code_with_otp()
        
        # Step 2: Exchange for token
        print("\n📡 Step 2: Exchanging code for access token...")
        token, expiry = get_access_token(auth_code)
        
        # Step 3: Update credential file
        print("\n📡 Step 3: Updating credential file...")
        update_cred_file(token, expiry)
        
        print("\n" + "=" * 60)
        print("✅ All done! Token updated successfully")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
