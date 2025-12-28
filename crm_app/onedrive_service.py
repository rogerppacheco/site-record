import requests
import urllib.parse
from django.conf import settings

class OneDriveUploader:
    def __init__(self):
        self.client_id = settings.MS_CLIENT_ID
        self.client_secret = settings.MS_CLIENT_SECRET
        self.refresh_token = settings.MS_REFRESH_TOKEN
        self.base_url = "https://graph.microsoft.com/v1.0"

    def get_access_token(self):
        """Usa o Refresh Token eterno para pegar um token de acesso temporário"""
        url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
            'scope': 'Files.ReadWrite.All'
        }
        r = requests.post(url, data=data)
        if r.status_code == 200:
            return r.json().get('access_token')
        raise Exception(f"Erro ao renovar token OneDrive: {r.text}")

    def upload_file(self, file_obj, folder_name, filename):
        """
        Sobe arquivo para: /CDOI_Record_Vertical/{folder_name}/{filename}
        Retorna o Link de Visualização (webUrl)
        """
        token = self.get_access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/octet-stream'
        }
        
        # Codifica nomes para URL (evita erro com espaços e acentos)
        root = settings.MS_DRIVE_FOLDER_ROOT
        safe_folder = urllib.parse.quote(folder_name)
        safe_filename = urllib.parse.quote(filename)
        
        # Caminho completo na API do Graph
        url = f"{self.base_url}/me/drive/root:/{root}/{safe_folder}/{safe_filename}:/content"
        
        # Lê o arquivo da memória
        content = file_obj.read()
        
        resp = requests.put(url, headers=headers, data=content)
        
        if resp.status_code in [200, 201]:
            data = resp.json()
            return data.get('webUrl') # Link para acessar o arquivo
        else:
            raise Exception(f"Erro Upload OneDrive: {resp.text}")