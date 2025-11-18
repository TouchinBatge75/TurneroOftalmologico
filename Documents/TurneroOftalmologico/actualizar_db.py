# actualizar_db.py
import sqlite3

def get_db_connection():
    conn = sqlite3.connect('turnos.db')
    conn.row_factory = sqlite3.Row
    return conn

def actualizar_base_datos():
    conn = get_db_connection()
    try:
        # Agregar columna estado_detallado si no existe
        conn.execute('''
            ALTER TABLE doctores ADD COLUMN estado_detallado TEXT DEFAULT "DISPONIBLE"
        ''')
        conn.commit()
        print("✅ Base de datos actualizada: columna 'estado_detallado' agregada")
        
        # Actualizar los valores existentes
        conn.execute('UPDATE doctores SET estado_detallado = "DISPONIBLE" WHERE activo = 1')
        conn.execute('UPDATE doctores SET estado_detallado = "AUSENTE" WHERE activo = 0')
        conn.commit()
        print("✅ Valores actualizados en doctores existentes")
        
        return True
        
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️ La columna 'estado_detallado' ya existe")
            return True
        else:
            print(f"❌ Error: {e}")
            return False
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        return False
    finally:
        conn.close()

if __name__ == '__main__':
    print("🔄 Actualizando base de datos...")
    if actualizar_base_datos():
        print("🎉 Base de datos actualizada exitosamente!")
    else:
        print("💥 Error al actualizar la base de datos")