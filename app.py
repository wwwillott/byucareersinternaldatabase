from flask import Flask, request, render_template, redirect, url_for
import pyodbc
import os

app = Flask(__name__)

# Azure SQL connection string details (move to env vars in prod)
server = '<your-server>.database.windows.net'
database = '<your-db>'
username = '<your-user>'
password = '<your-password>'
driver = '{ODBC Driver 17 for SQL Server}'
conn_str = f'DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}'

def get_connection():
    return pyodbc.connect(conn_str)

@app.route('/')
def index():
    return redirect(url_for('editor'))

@app.route('/editor')
def editor():
    conn = get_connection()
    cursor = conn.cursor()

    # Get column names
    cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='entries'")
    columns = [row[0] for row in cursor.fetchall()]
    conn.close()

    return render_template('editor.html', columns=columns)

@app.route('/add_column', methods=['POST'])
def add_column():
    column_name = request.form['column_name']
    column_type = request.form['column_type']  # e.g. VARCHAR(100), INT, etc.
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"ALTER TABLE entries ADD [{column_name}] {column_type}")
    conn.commit()
    conn.close()
    return redirect(url_for('editor'))

@app.route('/add_row', methods=['POST'])
def add_row():
    conn = get_connection()
    cursor = conn.cursor()

    # Dynamically build insert query
    columns = []
    values = []
    for key, value in request.form.items():
        if key.startswith("column_") and value != "":
            column = key.replace("column_", "")
            columns.append(f"[{column}]")
            values.append(f"'{value}'")  # You may want to escape values or use parameters

    if columns:
        query = f"INSERT INTO entries ({', '.join(columns)}) VALUES ({', '.join(values)})"
        cursor.execute(query)
        conn.commit()
    conn.close()
    return redirect(url_for('editor'))

@app.route('/test')
def test():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TOP 5 * FROM your_table_name")  # Replace with your real table name
    rows = cursor.fetchall()
    conn.close()
    return '<br>'.join([str(row) for row in rows])

if __name__ == '__main__':
    app.run(debug=True)
