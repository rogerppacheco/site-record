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
    
    def upload_file_and_get_download_url(self, file_obj, folder_name, filename):
        """
        Sobe arquivo para OneDrive, cria link compartilhado público e retorna URL de download direto.
        Ideal para enviar arquivos grandes via WhatsApp.
        Retorna: URL de download direto (downloadUrl) ou webUrl como fallback
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            token = self.get_access_token()
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/octet-stream'
            }
            
            # Codifica nomes para URL (evita erro com espaços e acentos)
            root = settings.MS_DRIVE_FOLDER_ROOT
            safe_folder = urllib.parse.quote(folder_name)
            safe_filename = urllib.parse.quote(filename)
            
            # 1. Upload do arquivo
            upload_url = f"{self.base_url}/me/drive/root:/{root}/{safe_folder}/{safe_filename}:/content"
            
            # Ler conteúdo (se file_obj já foi lido, precisa resetar)
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
            content = file_obj.read()
            
            logger.info(f"[OneDrive] Fazendo upload: {folder_name}/{filename} ({len(content)} bytes)")
            resp = requests.put(upload_url, headers=headers, data=content)
            
            if resp.status_code not in [200, 201]:
                raise Exception(f"Erro Upload OneDrive: {resp.text}")
            
            upload_data = resp.json()
            item_id = upload_data.get('id')
            
            if not item_id:
                # Fallback: retornar webUrl se não conseguir item_id
                logger.warning(f"[OneDrive] Não conseguiu item_id, usando webUrl como fallback")
                return upload_data.get('webUrl')
            
            # 2. Criar link compartilhado público (anônimo)
            share_url = f"{self.base_url}/me/drive/items/{item_id}/createLink"
            share_headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            share_payload = {
                "type": "view",
                "scope": "anonymous"
            }
            
            logger.info(f"[OneDrive] Criando link compartilhado para item {item_id}")
            share_resp = requests.post(share_url, headers=share_headers, json=share_payload)
            
            if share_resp.status_code == 200:
                share_data = share_resp.json()
                share_link = share_data.get('link', {}).get('webUrl')
                
                if share_link:
                    # 3. Obter downloadUrl usando o share link
                    # Converter share link para encoded format
                    import base64
                    encoded_url = base64.b64encode(share_link.encode()).decode().rstrip('=').replace('/', '_').replace('+', '-')
                    share_id = f"u!{encoded_url}"
                    
                    # Buscar downloadUrl
                    download_info_url = f"{self.base_url}/shares/{share_id}/driveItem?$select=@microsoft.graph.downloadUrl,name"
                    download_headers = {'Authorization': f'Bearer {token}'}
                    
                    logger.info(f"[OneDrive] Obtendo downloadUrl do item compartilhado")
                    download_resp = requests.get(download_info_url, headers=download_headers)
                    
                    if download_resp.status_code == 200:
                        download_data = download_resp.json()
                        download_url = download_data.get('@microsoft.graph.downloadUrl')
                        if download_url:
                            logger.info(f"[OneDrive] ✅ DownloadUrl obtido com sucesso")
                            return download_url
                    
                    # Fallback: usar share_link direto (pode funcionar)
                    logger.warning(f"[OneDrive] Não conseguiu downloadUrl, usando share_link")
                    return share_link
            
            # Fallback final: usar webUrl
            logger.warning(f"[OneDrive] Não conseguiu criar link compartilhado, usando webUrl")
            return upload_data.get('webUrl')
            
        except Exception as e:
            logger.error(f"[OneDrive] ❌ Erro ao fazer upload e obter downloadUrl: {e}")
            import traceback
            traceback.print_exc()
            raise