# actualizar_db.py
import sqlite3

@app.route('/api/actualizar-bd')
def actualizar_bd():
    conn = get_db_connection()
    try:
        # Agregar columna estado_detallado si no existe
        conn.execute('''
            ALTER TABLE doctores ADD COLUMN estado_detallado TEXT DEFAULT "DISPONIBLE"
        ''')
        conn.commit()
        return jsonify({'success': True, 'message': 'BD actualizada'})
    except Exception as e:
        print(f"La columna probablemente ya existe: {e}")
        return jsonify({'success': True, 'message': 'BD ya está actualizada'})
    finally:
        conn.close()

if __name__ == '__main__':
    actualizar_base_datos()