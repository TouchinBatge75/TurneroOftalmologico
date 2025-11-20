# limpiar_todo_ahora.py
import sqlite3

def limpiar_todo():
    print("🧹 LIMPIANDO TODO EL SISTEMA")
    print("=" * 40)
    
    conn = sqlite3.connect('turnos.db')
    
    # 1. Liberar TODOS los consultorios
    conn.execute('UPDATE consultorios SET ocupado = 0, doctor_actual = NULL, timestamp_ocupado = NULL')
    consultorios_liberados = conn.execute('SELECT changes()').fetchone()[0]
    
    # 2. Poner TODOS los doctores como ausentes
    conn.execute('UPDATE doctores SET activo = 0, estado_detallado = "AUSENTE"')
    doctores_actualizados = conn.execute('SELECT changes()').fetchone()[0]
    
    conn.commit()
    
    # 3. Verificar resultado
    consultorios = conn.execute('SELECT numero, ocupado FROM consultorios').fetchall()
    doctores = conn.execute('SELECT nombre, activo FROM doctores').fetchall()
    
    print(f"✅ {consultorios_liberados} consultorios liberados")
    print(f"✅ {doctores_actualizados} doctores marcados como ausentes")
    
    print("\n📊 ESTADO FINAL:")
    print("Consultorios:")
    for c in consultorios:
        estado = "🔴 OCUPADO" if c[1] == 1 else "🟢 LIBRE"
        print(f"   {c[0]}: {estado}")
    
    print("\nDoctores:")
    for d in doctores:
        estado = "🟢 ACTIVO" if d[1] == 1 else "🔴 AUSENTE"
        print(f"   {d[0]}: {estado}")
    
    conn.close()
    print("\n🎯 ¡Sistema completamente limpiado!")

if __name__ == '__main__':
    limpiar_todo()