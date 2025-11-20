# verificar_estado_actual.py
import sqlite3

def verificar_estado_actual():
    print("🔍 VERIFICANDO ESTADO ACTUAL DE LA BASE DE DATOS")
    print("=" * 50)
    
    conn = sqlite3.connect('turnos.db')
    
    # 1. Verificar si la tabla de consultorios existe
    try:
        consultorios = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='consultorios'").fetchone()
        if consultorios:
            print("✅ Tabla 'consultorios' EXISTE en la base de datos")
        else:
            print("❌ Tabla 'consultorios' NO EXISTE")
            return
    except Exception as e:
        print(f"❌ Error verificando tabla: {e}")
        return
    
    # 2. Verificar consultorios y su estado
    print("\n📊 ESTADO DE CONSULTORIOS:")
    consultorios = conn.execute('''
        SELECT c.id, c.numero, c.ocupado, c.doctor_actual, d.nombre as doctor_nombre
        FROM consultorios c 
        LEFT JOIN doctores d ON c.doctor_actual = d.id
        ORDER BY c.numero
    ''').fetchall()
    
    for c in consultorios:
        estado = "🔴 OCUPADO" if c[2] == 1 else "🟢 LIBRE"
        doctor = c[4] if c[4] else "Ninguno"
        print(f"   {c[1]} (ID:{c[0]}): {estado} | Doctor: {doctor}")
    
    # 3. Verificar doctores activos
    print("\n👨‍⚕️ DOCTORES ACTIVOS:")
    doctores_activos = conn.execute('SELECT id, nombre FROM doctores WHERE activo = 1').fetchall()
    if doctores_activos:
        for d in doctores_activos:
            print(f"   {d[1]} (ID:{d[0]}): 🟢 ACTIVO")
    else:
        print("   ✅ No hay doctores activos")
    
    conn.close()

if __name__ == '__main__':
    verificar_estado_actual()