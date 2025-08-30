import mysql.connector
from getpass import getpass
import os
from urllib.parse import urlparse

def inspecionar_banco():
    """
    Este script se conecta a um banco de dados MySQL para listar todas as tabelas
    e suas chaves estrangeiras. Ele detecta automaticamente as credenciais do Heroku
    se a variável de ambiente JAWSDB_URL estiver disponível.
    """
    db_config = {}
    
    # --- Detecção Automática de Credenciais do Heroku ---
    db_url = os.getenv('JAWSDB_URL')
    
    if db_url:
        print("Credenciais do Heroku (JAWSDB_URL) detectadas. Conectando automaticamente...")
        parsed_url = urlparse(db_url)
        db_config = {
            'host': parsed_url.hostname,
            'database': parsed_url.path.lstrip('/'),
            'user': parsed_url.username,
            'password': parsed_url.password,
            'port': parsed_url.port or '3306'
        }
    else:
        # --- Coleta Manual Segura das Credenciais (Fallback) ---
        print("Variável de ambiente JAWSDB_URL não encontrada.")
        print("Por favor, insira as credenciais manualmente.")
        db_config = {
            'host': input("Host do Banco de Dados: "),
            'database': input("Nome do Banco de Dados (Database): "),
            'user': input("Usuário: "),
            'password': getpass("Senha: "),
            'port': input("Porta (padrão 3306): ") or '3306'
        }

    try:
        print(f"\nConectando ao host '{db_config['host']}'...")
        
        # --- Conexão ---
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        print("Conexão bem-sucedida!")

        # --- Listar Tabelas ---
        print("\n--- LISTA DE TABELAS NO BANCO NOVO ---")
        cursor.execute("SHOW TABLES;")
        tabelas = [table[0] for table in cursor.fetchall()]
        for tabela in tabelas:
            print(f"- {tabela}")

        # --- Listar Chaves Estrangeiras (Relacionamentos) ---
        print("\n--- RELACIONAMENTOS (CHAVES ESTRANGEIRAS) ---")
        query_fks = """
            SELECT 
                kcu.table_name AS tabela_filha,
                kcu.column_name AS coluna_filha,
                kcu.referenced_table_name AS tabela_pai,
                kcu.referenced_column_name AS coluna_pai
            FROM 
                information_schema.key_column_usage AS kcu
            WHERE 
                kcu.referenced_table_schema = %s
                AND kcu.referenced_table_name IS NOT NULL;
        """
        cursor.execute(query_fks, (db_config['database'],))
        
        relacionamentos = cursor.fetchall()
        if not relacionamentos:
            print("Nenhum relacionamento (chave estrangeira) encontrado.")
        else:
            for rel in relacionamentos:
                tabela_filha, coluna_filha, tabela_pai, coluna_pai = rel
                print(f"- A tabela '{tabela_filha}' se conecta com '{tabela_pai}' (através de '{tabela_filha}.{coluna_filha}' -> '{tabela_pai}.{coluna_pai}')")

    except mysql.connector.Error as err:
        print(f"\nErro de banco de dados: {err}")
        print("Verifique se as credenciais estão corretas e se a aplicação tem permissão para acessar o banco.")
    
    finally:
        # --- Fechar Conexão ---
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            print("\nConexão fechada.")

if __name__ == "__main__":
    inspecionar_banco()