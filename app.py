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
def home():
    return redirect('/editor')

@app.route('/editor')
def editor():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_NAME = 'Employers'
    """)
    columns = [row[0] for row in cursor.fetchall()]
    print("🧪 Columns from DB:", columns) 
    conn.close()

    return render_template('editor.html', columns=columns)

@app.route('/add_row', methods=['POST'])
def add_row():
    print("Row added!")
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
        query = f"INSERT INTO Employers ({column_names}) VALUES ({placeholders})"
        cursor.execute(query, tuple(values))
        conn.commit()

    conn.close()
    return redirect('/editor')

if __name__ == '__main__':
    app.run(debug=True)