from flask import Flask, request, render_template, redirect
import pymssql  # uses easier connection than pyodbc

app = Flask(__name__)

def get_connection():
    return pymssql.connect(
        server='byucareerservices.database.windows.net',
        user='willott@byucareerservices.database.windows.net',
        password='Willisthebest17',
        database='Career_Services_Database'
    )

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/editor/<table_name>')
def editor(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table_name,))
    columns = [row[0] for row in cursor.fetchall()]

    conn.close()
    return render_template('editor.html', table_name=table_name, columns=columns)

@app.route('/add_row/<table_name>', methods=['POST'])
def add_row(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    conn = get_connection()
    cursor = conn.cursor()

    columns = []
    values = []

    for key, value in request.form.items():
        if key.startswith("column_") and value.strip():
            column = key.replace("column_", "")
            columns.append(column)
            values.append(value.strip())

    if columns:
        placeholders = ', '.join(['%s'] * len(values))
        column_names = ', '.join(columns)
        query = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"
        cursor.execute(query, tuple(values))
        conn.commit()

    conn.close()
    return redirect(f'/view/{table_name}')


@app.route('/view/<table_name>', methods=['GET', 'POST'])
def view_table(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    conn = get_connection()
    cursor = conn.cursor()

    # Get all column names (always needed for checkboxes)
    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (table_name,))
    all_columns = [row[0] for row in cursor.fetchall()]

    # If POST, filter selected columns
    selected_columns = request.form.getlist('columns') if request.method == 'POST' else all_columns

    if not selected_columns:
        selected_columns = all_columns  # fallback if nothing selected

    column_str = ', '.join(f'[{col}]' for col in selected_columns)  # [] for SQL Server compatibility
    cursor.execute(f"SELECT {column_str} FROM {table_name}")
    rows = cursor.fetchall()

    conn.close()
    return render_template(
        'viewer.html',
        table_name=table_name,
        columns=selected_columns,
        rows=rows,
        all_columns=all_columns,
        selected_columns=selected_columns
    )

@app.route('/delete/<int:EmployerID>', methods=['POST'])
def delete_row(EmployerID):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM Employers WHERE EmployerID = %s", (EmployerID,))
    conn.commit()
    conn.close()

    return redirect('/viewer')

if __name__ == '__main__':
    app.run(debug=True)