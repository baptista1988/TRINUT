<<<<<<< HEAD
import psycopg2

# Parâmetros de conexão do Supabase
HOST = "aws-0-eu-west-1.pooler.supabase.com"
PORT = 6543
DATABASE = "postgres"
USER = "postgres.fconcnqghekmsgvzpgtn"

# ⚠️ COLOQUE A SUA SENHA DENTRO DAS ASPAS ABAIXO:
PASSWORD = "uXbQ65NDnOkA3L6Q"

def testar_conexao():
    try:
        print("A ligar ao Supabase...")
        
        # Estabelece a conexão com os parâmetros
        connection = psycopg2.connect(
            host=HOST,
            port=PORT,
            dbname=DATABASE,
            user=USER,
            password=PASSWORD
        )
        
        print("✅ Conexão estabelecida com sucesso!")
        
        # Teste rápido executando uma consulta
        cursor = connection.cursor()
        cursor.execute("SELECT version();")
        db_version = cursor.fetchone()
        print(f"Versão do PostgreSQL: {db_version[0]}")
        
        # Fecha o cursor e a conexão
        cursor.close()
        connection.close()
        print("Conexão encerrada com sucesso.")

    except Exception as e:
        print(f"❌ Erro ao conectar ao Supabase: {e}")

if __name__ == "__main__":
=======
import psycopg2

# Parâmetros de conexão do Supabase
HOST = "aws-0-eu-west-1.pooler.supabase.com"
PORT = 6543
DATABASE = "postgres"
USER = "postgres.fconcnqghekmsgvzpgtn"

# ⚠️ COLOQUE A SUA SENHA DENTRO DAS ASPAS ABAIXO:
PASSWORD = "UuBsn8b1RbzeI3hN"

def testar_conexao():
    try:
        print("A ligar ao Supabase...")
        
        # Estabelece a conexão com os parâmetros
        connection = psycopg2.connect(
            host=HOST,
            port=PORT,
            dbname=DATABASE,
            user=USER,
            password=PASSWORD
        )
        
        print("✅ Conexão estabelecida com sucesso!")
        
        # Teste rápido executando uma consulta
        cursor = connection.cursor()
        cursor.execute("SELECT version();")
        db_version = cursor.fetchone()
        print(f"Versão do PostgreSQL: {db_version[0]}")
        
        # Fecha o cursor e a conexão
        cursor.close()
        connection.close()
        print("Conexão encerrada com sucesso.")

    except Exception as e:
        print(f"❌ Erro ao conectar ao Supabase: {e}")

if __name__ == "__main__":
>>>>>>> f36770e1a5ff03f01539c09334820fbd5b959928
    testar_conexao()