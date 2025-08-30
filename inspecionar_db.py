import mysql.connector
from getpass import getpass

def inspecionar_banco():
    """
    Este script se conecta a um banco de dados MySQL para listar todas as tabelas
    e suas chaves estrangeiras. É útil para mapear a estrutura de um banco de dados
    existente para uma migração de dados.
    """
    try:
        # --- Coleta Segura das Credenciais ---
        # Usamos input e getpass para evitar deixar as credenciais no código.
        host = input("Host do Banco de Dados: ")
        database = input("Nome do Banco de Dados (Database): ")
        user = input("Usuário: ")
        password = getpass("Senha: ")
        port = input("Porta (padrão 3306): ") or '3306'

        print("\nConectando ao banco de dados...")
        
        # --- Conexão ---
        conn = mysql.connector.connect(
            host=host,
            database=database,
            user=user,
            password=password,
            port=port
        )
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
        cursor.execute(query_fks, (database,))
        
        relacionamentos = cursor.fetchall()
        if not relacionamentos:
            print("Nenhum relacionamento (chave estrangeira) encontrado.")
        else:
            for rel in relacionamentos:
                tabela_filha, coluna_filha, tabela_pai, coluna_pai = rel
                print(f"- A tabela '{tabela_filha}' se conecta com '{tabela_pai}' (através de '{tabela_filha}.{coluna_filha}' -> '{tabela_pai}.{coluna_pai}')")

    except mysql.connector.Error as err:
        print(f"\nErro de banco de dados: {err}")
        print("Verifique se as credenciais estão corretas e se o seu IP tem permissão para acessar o banco.")
    
    finally:
        # --- Fechar Conexão ---
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            print("\nConexão fechada.")

if __name__ == "__main__":
    inspecionar_banco()
