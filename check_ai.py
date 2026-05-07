import sys
import os

# Add current directory to path
sys.path.insert(0, os.getcwd())

from safari.ai_client import get_provider_status

def main():
    print("\n--- Safari AI Status Diagnostic ---")
    status = get_provider_status()
    
    # 1. Gemini Status
    g = status["gemini"]
    print(f"\nGoogle Gemini:")
    print(f"   Status:  {'ONLINE' if g['available'] else 'OFFLINE'}")
    print(f"   Model:   {g['model']}")
    print(f"   API Key: {'Configured' if g['api_key_set'] else 'Missing'}")
    if g['disabled']:
        print(f"   WARNING: Gemini was DISABLED after {g['fail_count']} failed attempts.")
        
    # 2. Ollama Status
    o = status["ollama"]
    print(f"\nLocal Ollama:")
    print(f"   Status:  {'ONLINE' if o['available'] else 'OFFLINE'}")
    print(f"   URL:     {o['url']}")
    print(f"   Model:   {o['model']}")
    
    # 3. Final Conclusion
    print("\n--- Result ---")
    if status["primary"] == "gemini":
        print("SUCCESS: Safari is using the Cloud Gemini API for maximum performance.")
    else:
        print("FALLBACK: Safari is using your Local Ollama model (Gemini is unavailable).")
    print("--------------------------------------\n")

if __name__ == "__main__":
    main()
