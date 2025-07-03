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

def get_primary_key_column(table_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE OBJECTPROPERTY(
          OBJECT_ID(CONSTRAINT_SCHEMA + '.' + CONSTRAINT_NAME),
          'IsPrimaryKey'
        ) = 1
        AND TABLE_NAME = '{table_name}'
    """)
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

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
        if key.startswith("column_") and value.strip() != '':
            column_name = key.replace("column_", "")
            columns.append(column_name)
            values.append(value.strip())

    if columns:
        placeholders = ', '.join(['%s'] * len(values))
        column_names = ', '.join(columns)
        query = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"
        cursor.execute(query, tuple(values))
        conn.commit()

    conn.close()
    return redirect(f'/view/{table_name}')

@app.route('/editor_wizard/<table_name>')
def editor_wizard(table_name):
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

    column_descriptions = {
        'EventID': 'To get the ID, go to the Info Session on Handshake and copy the number from the URL.',
        'EmployerID': 'To get the ID, go to the Employer on Handshake and copy the number from the URL.',
        'InterviewID': 'To get the ID, go to the Interview on Handshake and copy the number from the URL.'
    }

    dropdown_options = {
        'RoomType': ['Pre-Select', 'Room Only'],
        'Weekday': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    }

    return render_template('editor_wizard.html',
                           table_name=table_name,
                           columns=columns,
                           column_descriptions=column_descriptions,
                           dropdown_options=dropdown_options)


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

@app.route('/delete_mode/<table_name>')
def delete_mode(table_name):
    allowed_tables = ['InfoSessions', 'Interviews', 'Employers']
    if table_name not in allowed_tables:
        return "Table not found", 404

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = '{table_name}' 
        ORDER BY ORDINAL_POSITION
    """)
    columns = [row[0] for row in cursor.fetchall()]
    pk_column = get_primary_key_column(table_name) or columns[0]  # Fallback to first column if no PK found

    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()

    conn.close()
    return render_template('delete_mode.html', table_name=table_name, columns=columns, rows=rows, pk_column=pk_column)


@app.route('/confirm_delete/<table_name>', methods=['POST'])
def confirm_delete(table_name):
    row_ids = request.form.getlist('row_ids')
    pk_column = request.form.get('pk_column')
    return render_template('confirm_delete.html', table_name=table_name, row_ids=row_ids, pk_column=pk_column)


@app.route('/final_delete/<table_name>', methods=['POST'])
def final_delete(table_name):
    row_ids = request.form.getlist('row_ids')
    pk_column = request.form.get('pk_column')
    if not row_ids or not pk_column:
        return redirect(f'/view/{table_name}')

    conn = get_connection()
    cursor = conn.cursor()

    print("Deleting from:", table_name)
    print("PK column:", pk_column)
    print("Row IDs:", row_ids)

    # Assumes first column is primary key
    placeholders = ','.join(['%s'] * len(row_ids))
    query = f"DELETE FROM {table_name} WHERE {pk_column} IN ({placeholders})"
    cursor.execute(query, tuple(row_ids))
    conn.commit()
    conn.close()

    return redirect(f'/view/{table_name}')

if __name__ == '__main__':
    app.run(debug=True)