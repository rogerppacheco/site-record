import requests

# Dados que você forneceu
client_id = "8bf70341-60b1-47c6-a5ea-98db4e12859d"
client_secret = ""

# O código gigante que veio na sua URL de erro (eu já copiei ele daqui)
code = "1.Ab0A_qfmfkcUckeuNPwgWi3q10ED94uxYMZHpeqY204ShZ3LAM29AA.AgABBAIAAABlMNzVhAPUTrARzfQjWPtKAwDs_wUA9P9Fdm9TdHNBcnRpZmFjdHMCAAAAAADuZRlDaTcaCrTRPFrclzJqiVx0ZlYC_gEQffPlY7PHyguCZb1pHWp0AERFjtdbfy8s-v2qGbHQyiZAwDgIrq7bQuww8SrSiHh8eeOXdUu4keDuGSg7Uk9pNGphU59HVKe0A59qPfSSlF55qqbSW-ph0-QoqjKn6AsNhHmHQfLi4nxyiOaMqk5s98YEb7SE28a6Oi9hD8uGy37ohA_ulDLJG3pgm-Qgy69-RmKlvavidN5fgIAPbX998M8GnqGj5AqEXolYgZl5WQ8DO3CoCWBA3BnpQlUL1qj_xATHBtNr_W-cmWaEta_nzMPeQzlCKgFrCWjTijpjHWNK-1EfTHMIIMNcMMO15yH67pTSS5l_ImsO8zO89FyNVf0grjzFfxqd3Aaigb6OQTWJTM_YTXOWYUMB-iUviOC3_3f-t-WirSX_gB6BrnJH1Yy5emzJaVgMef7nQIVWO0UPx-_dz86quGDRK6M1lQPolGiDn1au3NzQaj-_3XYcd6Utl5u3Ckkr4OSecDuzsIdfB2sAF_pc6DnrKH3gt8Yi3yWv2S_oCMEZZw--g6SBqaeALAiZuz8qjbwTkw4vg3qeS3j5WvhIYB8EckIWxlxhGp3MeY8fHjdfef-CP-hS7H1o-QdVN_pNrEWzwgisuOKoJgzTogqq2qI1ardjzEcaF5-xqSMNKQPuJzhiKUOQ7TxZIKCh93yH7s-1RWGnqk8pcIkdsy11o3MDOhttgsqgOmV5vgH7ej_iyaCfHNwHsAanXqeK4UGONQS6"

url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

data = {
    'client_id': client_id,
    'scope': 'Files.ReadWrite.All offline_access',
    'code': code,
    'redirect_uri': 'http://localhost:8000/callback',
    'grant_type': 'authorization_code',
    'client_secret': client_secret
}

print("Contactando a Microsoft para gerar o Token Permanente...")
try:
    r = requests.post(url, data=data)
    r.raise_for_status() # Verifica se deu erro HTTP
    tokens = r.json()
    
    refresh_token = tokens.get('refresh_token')
    
    print("\n" + "="*60)
    print("SUCESSO! AQUI ESTÁ SEU REFRESH TOKEN:")
    print("="*60)
    print(refresh_token)
    print("="*60 + "\n")
    print("Copie o código acima e coloque no seu settings.py na variável MS_REFRESH_TOKEN")

except Exception as e:
    print(f"\nERRO: {e}")
    if 'r' in locals():
        print("Detalhe do erro:", r.text)