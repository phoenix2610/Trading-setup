import requests
import gzip
import json
import os
import pyotp
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta

# Configuration
UPSTOX_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
NSE_JSON_PATH = "nse_main.json"
ENV_FILE = "Upstox_ENV.json"  #this is available in the same repo for you to download

def download_nse_instruments():
    """Download and extract NSE instruments from Upstox"""
    try:
        print("\n📥 Downloading NSE instruments from Upstox...")
        response = requests.get(UPSTOX_URL, stream=True)
        response.raise_for_status()
        
        # Decompress and save
        with gzip.open(response.raw, 'rb') as f_in:
            with open(NSE_JSON_PATH, 'wb') as f_out:
                f_out.write(f_in.read())
        
        print(f"✅ NSE instruments downloaded to {NSE_JSON_PATH}")
        return True
    except Exception as e:
        print(f"❌ Failed to download NSE instruments: {e}")
        return False

def load_env():
    """Load or create ENV.json"""
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r') as f:
            return json.load(f)
    else:
        # Create default structure
        env = {
            "upstox": {
                "api_key": "",
                "secret_api": "",
                "access_token": "",
                "expiry_date": "",
                "totp_secret": "",
                "redirect_url": "http://localhost"  #whatever you have kept while making the upstox Api
            }
        }
        with open(ENV_FILE, 'w') as f:
            json.dump(env, f, indent=4)
        print(f"⚠️  Created new {ENV_FILE}. Please fill in your API credentials.")
        return env

def save_env(env):
    """Save ENV.json"""
    with open(ENV_FILE, 'w') as f:
        json.dump(env, f, indent=4)

def get_nearest_nifty_expiry_from_json():
    """Parse nse_main.json to find the nearest NIFTY expiry date"""
    try:
        if not os.path.exists(NSE_JSON_PATH):
            print(f"⚠️  {NSE_JSON_PATH} not found, downloading...")
            if not download_nse_instruments():
                return get_nearest_thursday_fallback()
        
        with open(NSE_JSON_PATH, 'r') as f:
            instruments = json.load(f)
        
        today = datetime.now().date()
        nifty_expiries = set()
        
        # Parse through instruments to find NIFTY options
        for instrument in instruments:
            if isinstance(instrument, dict):
                name = instrument.get('name', '').upper()
                instrument_type = instrument.get('instrument_type', '').upper()
                
                # Look for NIFTY options
                if 'NIFTY' in name and instrument_type in ['CE', 'PE']:
                    expiry_str = instrument.get('expiry')
                    if expiry_str:
                        try:
                            # Parse expiry date
                            if isinstance(expiry_str, str):
                                expiry_date = datetime.strptime(expiry_str.split('T')[0], '%Y-%m-%d').date()
                            elif isinstance(expiry_str, int):
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
            print(f"✅ Found nearest NIFTY expiry: {nearest_expiry}")
            return datetime.combine(nearest_expiry, datetime.min.time())
        else:
            print("⚠️  No future NIFTY expiries found, using Thursday fallback")
            return get_nearest_thursday_fallback()
            
    except Exception as e:
        print(f"⚠️  Error parsing {NSE_JSON_PATH}: {e}")
        return get_nearest_thursday_fallback()

def get_nearest_thursday_fallback():
    """Fallback: Calculate the nearest Thursday for options expiry"""
    today = datetime.now()
    current_weekday = today.weekday()  # Monday=0, Sunday=6
    
    # Thursday is weekday 3
    if current_weekday < 3:
        days_until_thursday = 3 - current_weekday
    elif current_weekday == 3:
        days_until_thursday = 0
    else:
        days_until_thursday = (3 - current_weekday) % 7
    
    return today + timedelta(days=days_until_thursday)

def get_auth_code_with_otp(api_key, totp_secret, redirect_url):
    """Get auth code using TOTP without browser interaction"""
    try:
        if totp_secret:
            # Generate OTP directly using pyotp
            totp = pyotp.TOTP(totp_secret)
            otp_code = totp.now()
            print(f"\n🔐 Generated OTP: {otp_code}")
        else:
            print("\n⚠️  TOTP secret not configured")
        
        # Login URL
        url = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={api_key}&redirect_uri={redirect_url}"
        print(f"\n🔗 Login URL: {url}")
        if totp_secret:
            print(f"💡 Use OTP: {otp_code}")
        print("\n📋 Steps:")
        print("   1. Open the URL above in your browser")
        print("   2. Enter your credentials" + (" and the OTP shown above" if totp_secret else ""))
        print("   3. After login, copy the FULL redirect URL from browser")
        
        redirect = input("\n📌 Paste the full redirect URL here: ").strip()
        parsed = urlparse(redirect)
        code = parse_qs(parsed.query).get("code", [None])[0]
        if not code:
            raise ValueError("Auth code not found in URL.")
        return code
    except Exception as e:
        print(f"❌ Error getting auth code: {e}")
        raise

def get_access_token(auth_code, api_key, secret_api, redirect_url):
    """Exchange auth code for access token"""
    url = "https://api.upstox.com/v2/login/authorization/token"
    payload = {
        "code": auth_code,
        "client_id": api_key,
        "client_secret": secret_api,
        "redirect_uri": redirect_url,
        "grant_type": "authorization_code"
    }
    res = requests.post(url, data=payload)
    res.raise_for_status()
    data = res.json()
    
    # Get nearest expiry from JSON
    expiry_date = get_nearest_nifty_expiry_from_json()
    return data["access_token"], expiry_date

def main():
    print("=" * 60)
    print("🔄 Upstox Token & Expiry Updater")
    print("=" * 60)
    
    try:
        # Load environment
        env = load_env()
        upstox_config = env.get("upstox", {})
        
        # Validate credentials
        api_key = upstox_config.get("api_key")
        secret_api = upstox_config.get("secret_api")
        redirect_url = upstox_config.get("redirect_url", "http://localhost")
        totp_secret = upstox_config.get("totp_secret", "")
        
        if not api_key or not secret_api:
            print(f"\n❌ Please configure your API credentials in {ENV_FILE}")
            return
        
        # Step 1: Download NSE instruments
        print("\n📡 Step 1: Downloading NSE instruments...")
        download_nse_instruments()
        
        # Step 2: Get auth code
        print("\n📡 Step 2: Getting authorization code...")
        auth_code = get_auth_code_with_otp(api_key, totp_secret, redirect_url)
        
        # Step 3: Exchange for token
        print("\n📡 Step 3: Exchanging code for access token...")
        token, expiry = get_access_token(auth_code, api_key, secret_api, redirect_url)
        
        # Step 4: Update ENV.json
        print("\n📡 Step 4: Updating ENV.json...")
        upstox_config["access_token"] = token
        upstox_config["expiry_date"] = expiry.strftime("%Y-%m-%d")
        env["upstox"] = upstox_config
        save_env(env)
        
        print(f"\n✅ Token updated successfully!")
        print(f"📅 Expiry Date: {expiry.strftime('%Y-%m-%d')} ({expiry.strftime('%A')})")
        
        print("\n" + "=" * 60)
        print("✅ All done! Check ENV.json for updated credentials")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
