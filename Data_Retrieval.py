import psycopg2
import os
from dotenv import load_dotenv

class Database_Connector():
    def __init__(self):
        load_dotenv()
        try:
            self.conn = psycopg2.connect(
                database=os.getenv("DB_NAME"),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                host=os.getenv("DB_HOST"),
                port=os.getenv("DB_PORT")
            )
            self.cursor = self.conn.cursor()
        except Exception as e:
            raise RuntimeError(f"Unable to connect to PostgreSQL database. Error: {e}")

    def close_connection(self):
        self.cursor.close()
        self.conn.close()

    def retrieve_data(self, table_name, columns = None, condition = None):
        query = "SELECT "

        if columns is None:
            query += "*"
        else:
            for column in columns:
                query += "`" + column + "`, "

        query += " FROM `" + table_name + "` " + condition

        self.cursor.execute(query)
        data = self.cursor.fetchall()
        return data
