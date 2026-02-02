import pymysql
import sys

def check_mariadb_connection():
    DB_CONFIG = {
        "host": "ems.apollosupplychain.com",
        "port": 3306,
        "user": "ems-bi",
        "password": "Apollo@BI@2025",
        "database": "ems-warehouse-service",
        "connect_timeout": 10,
        "cursorclass": pymysql.cursors.DictCursor
    }

    print(f"--- Connecting to Remote MariaDB ---")
    print(f"Host: {DB_CONFIG['host']}")
    print(f"User: {DB_CONFIG['user']}")
    print(f"DB  : {DB_CONFIG['database']}")
    print("------------------------------------")

    try:
        connection = pymysql.connect(**DB_CONFIG)
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION() as version;")
            result = cursor.fetchone()
            cursor.execute("SHOW TABLES;")
            tables = cursor.fetchall()

        print("\n SUCCESS: Connection Established!")
        print(f" Server Version: {result['version']}")
        print(f"  Tables: {[list(t.values())[0] for t in tables]}")
        
        connection.close()
        return True

    except pymysql.err.OperationalError as e:
        code, message = e.args
        print(f"\n CONNECTION FAILED (Operational Error)")
        print(f"   Code: {code}")
        print(f"   Message: {message}")
        
        if code == 2003:
            print("   Check if your IP is whitelisted on the server 'ems.apollosupplychain.com'.")
                   
        
    except Exception as e:
        print(f"\n UNEXPECTED ERROR: {e}")

    return False

if __name__ == "__main__":
    try:
        import pymysql
    except ImportError:
        print("Please install the driver first: pip install pymysql")
        sys.exit(1)

    check_mariadb_connection()