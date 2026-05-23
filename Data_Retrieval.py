import psycopg2
import os
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor
from psycopg2 import sql


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
            self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        except Exception as e:
            raise RuntimeError(f"Unable to connect to PostgreSQL database. Error: {e}")

    def close_connection(self):
        self.cursor.close()
        self.conn.close()

    def retrieve_data(self, table_name, columns=None, condition=None, condition_values=None):
        # Handle dynamic column selection safely
        if columns is None:
            query = sql.SQL("SELECT * FROM {table}").format(
                table=sql.Identifier(table_name)
            )
        else:
            query = sql.SQL("SELECT {cols} FROM {table}").format(
                cols=sql.SQL(', ').join(map(sql.Identifier, columns)),
                table=sql.Identifier(table_name)
            )

        # Handle condition if it exists
        if condition:
            # Note: The condition string itself (e.g., "id = %s") is passed manually,
            # while the values are parameterized safely.
            query += sql.SQL(" WHERE " + condition)

        # Execute safely, passing values separate from the query
        self.cursor.execute(query, condition_values)
        return self.cursor.fetchall()

    def update_data(self, table_name, columns, new_data, condition=None, condition_values=None):
        # Build the "SET col1 = %s, col2 = %s" clause safely
        set_clause = sql.SQL(', ').join(
            sql.SQL("{} = %s").format(sql.Identifier(col)) for col in columns
        )

        query = sql.SQL("UPDATE {table} SET {set_clause}").format(
            table=sql.Identifier(table_name),
            set_clause=set_clause
        )

        if condition:
            query += sql.SQL(" WHERE " + condition)

        # Combine the new_data values with any condition values
        all_values = list(new_data)
        if condition_values:
            all_values.extend(condition_values)

        self.cursor.execute(query, all_values)
        self.conn.commit()  # Crucial: Commit the transaction

        return self.cursor.rowcount  # Returns the number of rows updated

    def insert_data(self, table_name, columns, data_values, returning_col=None):
        # Dynamically build the column names: "col1", "col2"
        cols = sql.SQL(', ').join(map(sql.Identifier, columns))

        # Dynamically build the exact number of %s placeholders needed
        placeholders = sql.SQL(', ').join([sql.Placeholder()] * len(columns))

        # Construct the base INSERT query
        query = sql.SQL("INSERT INTO {table} ({cols}) VALUES ({placeholders})").format(
            table=sql.Identifier(table_name),
            cols=cols,
            placeholders=placeholders
        )

        # If we need to return the newly created ID
        if returning_col:
            query += sql.SQL(" RETURNING {}").format(sql.Identifier(returning_col))
            self.cursor.execute(query, data_values)
            inserted_value = self.cursor.fetchone()[returning_col]
            self.conn.commit()  # Save changes
            return inserted_value

        # Standard execution if no return column is specified
        self.cursor.execute(query, data_values)
        self.conn.commit()  # Save changes
        return self.cursor.rowcount