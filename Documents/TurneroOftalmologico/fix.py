# fix_doctors.py
import sqlite3

def fix_doctors():
    conn = sqlite3.connect('turnos.db')
    
    # Poner todos los doctores como ausentes
    conn.execute('UPDATE doctores SET activo = 0, estado_detallado = "AUSENTE"')
    
    # Verificar los cambios
    doctors = conn.execute('SELECT id, nombre, activo, estado_detallado FROM doctores').fetchall()
    
    print("Doctores actualizados:")
    for doctor in doctors:
        print(f"  {doctor[1]} - Activo: {doctor[2]} - Estado: {doctor[3]}")
    
    conn.commit()
    conn.close()
    print("✅ Todos los doctores ahora están como AUSENTES")

if __name__ == '__main__':
    fix_doctors()