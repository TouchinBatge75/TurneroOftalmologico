# app.py
from flask import Flask, render_template, jsonify, request
import sqlite3
from estadisticas import registrar_historial, obtener_estadisticas_dia, obtener_estadisticas_mensual
from datetime import datetime

app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect('turnos.db', timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

@app.route('/')
def recepcion():
    return render_template('recepcion.html')

# API SIMPLIFICADA - SOLO ESTACIÓN ACTUAL
@app.route('/api/turnos')
def get_turnos():
    conn = get_db_connection()
    turnos = conn.execute('''
        SELECT t.*, 
               e.nombre as estacion_actual_nombre,
               d.nombre as doctor_nombre
        FROM turnos t
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        LEFT JOIN doctores d ON t.doctor_asignado = d.id
        WHERE t.estado != "FINALIZADO" AND t.estado != "CANCELADO"
        ORDER BY t.timestamp_creacion DESC
    ''').fetchall()
    conn.close()
    
    # DEBUG: Ver datos
    for turno in turnos:
        print(f"DEBUG: Turno {dict(turno)['numero']} - Doctor: {dict(turno)['doctor_nombre']}")
    
    return jsonify([dict(turno) for turno in turnos])

@app.route('/api/doctores')
def get_doctores():
    conn = get_db_connection()
    doctores = conn.execute('SELECT * FROM doctores WHERE activo = 1').fetchall()
    conn.close()
    return jsonify([dict(d) for d in doctores])

@app.route('/api/estaciones')
def get_estaciones_disponibles():
    conn = get_db_connection()
    estaciones = conn.execute('SELECT * FROM estaciones WHERE id != 1 AND id != 8').fetchall()
    conn.close()
    return jsonify([dict(e) for e in estaciones])

@app.route('/api/turnos/nuevo', methods=['POST'])
def crear_turno():
    data = request.json
    conn = None
    try:
        conn = get_db_connection()
        
        # Obtener fecha actual
        fecha_actual = datetime.now().strftime('%Y-%m-%d')
        
        # Buscar último turno de HOY
        ultimo_turno = conn.execute(
            'SELECT numero FROM turnos WHERE DATE(timestamp_creacion) = ? ORDER BY id DESC LIMIT 1',
            (fecha_actual,)
        ).fetchone()
        
        if ultimo_turno:
            # Extraer número del formato A001, A002, etc.
            ultimo_numero = int(ultimo_turno['numero'][1:])
            nuevo_numero = f"A{ultimo_numero + 1:03d}"
        else:
            # Primer turno del día
            nuevo_numero = "A001"
        
        estacion_inicial = data.get('estacion_inicial', 1)
        doctor_asignado = data.get('doctor_asignado') if estacion_inicial == 4 else None
        
        # INSERT SIMPLIFICADO - sin estacion_siguiente
        conn.execute('''
            INSERT INTO turnos (numero, paciente_nombre, paciente_edad, tipo, estacion_actual, doctor_asignado)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (nuevo_numero, data['paciente_nombre'], data['paciente_edad'], data['tipo'], estacion_inicial, doctor_asignado))
        
        # Obtener el ID del turno recién creado
        turno_id = conn.execute('SELECT last_insert_rowid() as id').fetchone()['id']
        
        # Registrar en historial
        registrar_historial(turno_id, 'CREADO', f'Tipo: {data["tipo"]}, Estación: {estacion_inicial}')
        
        conn.commit()
        
        return jsonify({'success': True, 'numero_turno': nuevo_numero, 'turno_id': turno_id})
        
    except Exception as e:
        print(f"Error al crear turno: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        if conn:
            conn.close()

# API para cancelacion de turnos
@app.route('/api/turnos/<int:turno_id>/cancelar', methods=['PUT'])
def cancelar_turno(turno_id):
    data = request.json
    razon = data.get('razon', 'No especificada') if data else 'No especificada'
    
    conn = get_db_connection()
    conn.execute('''
        UPDATE turnos 
        SET estado = "CANCELADO", timestamp_cancelado = CURRENT_TIMESTAMP, razon_cancelacion = ?
        WHERE id = ?
    ''', (razon, turno_id))
    conn.commit()
    conn.close()
    
    # Registrar en historial para estadísticas
    registrar_historial(turno_id, 'CANCELADO', f'Razón: {razon}', 'recepcion')
    
    return jsonify({'success': True})

@app.route('/api/turnos/<int:turno_id>/editar', methods=['PUT'])
def editar_turno(turno_id):
    data = request.json
    conn = get_db_connection()
    
    conn.execute('''
        UPDATE turnos 
        SET paciente_nombre = ?, paciente_edad = ?, tipo = ?, estacion_actual = ?, doctor_asignado = ?
        WHERE id = ?
    ''', (data['paciente_nombre'], data['paciente_edad'], data['tipo'], data['estacion_actual'], data.get('doctor_asignado'), turno_id))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# API: Obtener estadísticas del día
@app.route('/api/estadisticas/dia')
@app.route('/api/estadisticas/dia/<fecha>')
def get_estadisticas_dia(fecha=None):
    try:
        stats = obtener_estadisticas_dia(fecha)
        print(f"📊 Estadísticas del día {fecha}: {stats}")  # Debug
        return jsonify(stats)
    except Exception as e:
        print(f"Error en API estadísticas día: {e}")
        return jsonify({'error': str(e)}), 500

# API: Obtener estadísticas del mes
@app.route('/api/estadisticas/mes')
@app.route('/api/estadisticas/mes/<mes>/<anio>')
def get_estadisticas_mes(mes=None, anio=None):
    try:
        mes = int(mes) if mes else None
        anio = int(anio) if anio else None
        stats = obtener_estadisticas_mensual(mes, anio)
        print(f"Estadísticas del mes {mes}/{anio}: {stats}")  # Debug
        return jsonify(stats)
    except Exception as e:
        print(f"Error en API estadísticas mes: {e}")
        return jsonify({'error': str(e)}), 500
    

    # API: Obtener TODOS los doctores (activos e inactivos)
@app.route('/api/doctores/todos')
def get_todos_doctores():
    conn = get_db_connection()
    doctores = conn.execute('SELECT * FROM doctores ORDER BY nombre').fetchall()
    conn.close()
    return jsonify([dict(d) for d in doctores])


# API: Agregar nuevo doctor
@app.route('/api/doctores/nuevo', methods=['POST'])
def agregar_doctor():
    data = request.json
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO doctores (nombre, especialidad)
        VALUES (?, ?)
    ''', (data['nombre'], data['especialidad']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# API: Eliminar doctor
@app.route('/api/doctores/<int:doctor_id>', methods=['DELETE'])
def eliminar_doctor(doctor_id):
    conn = get_db_connection()
    
    turnos_activos = conn.execute('''
        SELECT COUNT(*) as count FROM turnos 
        WHERE doctor_asignado = ? AND estado IN ("PENDIENTE", "EN_ATENCION")
    ''', (doctor_id,)).fetchone()

    
    if turnos_activos > 0:
        conn.close()
        return jsonify({
            'success': False, 
            'error': f'No se puede eliminar doctor con {turnos_activos} turnos activos'
        })
    
    conn.execute('DELETE FROM doctores WHERE id = ?', (doctor_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/doctor-login')
def doctor_login_page():
    return render_template('doctor_login.html')

# Ruta para el login de doctores
@app.route('/api/doctor/login', methods=['POST'])
def doctor_login():
    data = request.json
    conn = get_db_connection()
    
    try:
        # Actualizar estado del doctor a ACTIVO
        conn.execute('UPDATE doctores SET activo = 1 WHERE id = ?', (data['doctor_id'],))
        
        # Obtener nombre del doctor para la respuesta
        doctor = conn.execute('SELECT nombre FROM doctores WHERE id = ?', (data['doctor_id'],)).fetchone()
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'doctor_nombre': doctor['nombre'],
            'message': 'Sesión iniciada correctamente'
        })
        
    except Exception as e:
        print(f"Error en login doctor: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/doctor-dashboard')
def doctor_dashboard():
    return render_template('doctor_dashboard.html')

# API para obtener turnos del doctor
@app.route('/api/doctor/turnos')
def get_turnos_doctor():
    doctor_id = request.args.get('doctor_id')
    conn = get_db_connection()
    
    turnos = conn.execute('''
        SELECT t.*, e.nombre as estacion_actual_nombre
        FROM turnos t
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        WHERE t.doctor_asignado = ? AND t.estado = "PENDIENTE"
        ORDER BY t.timestamp_creacion ASC
    ''', (doctor_id,)).fetchall()
    
    conn.close()
    return jsonify([dict(turno) for turno in turnos])

# API para llamar siguiente paciente
@app.route('/api/doctor/llamar-siguiente', methods=['POST'])
def llamar_siguiente_paciente():
    data = request.json
    doctor_id = data.get('doctor_id')
    
    conn = get_db_connection()
    
    # Obtener el siguiente turno en cola para este doctor
    turno = conn.execute('''
        SELECT t.*, e.nombre as estacion_actual_nombre
        FROM turnos t
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        WHERE t.doctor_asignado = ? AND t.estado = "PENDIENTE"
        ORDER BY t.timestamp_creacion ASC
        LIMIT 1
    ''', (doctor_id,)).fetchone()
    
    if not turno:
        conn.close()
        return jsonify({'success': False, 'error': 'No hay pacientes en espera'})
    
    # Actualizar estado del turno a "EN_ATENCION"
    conn.execute('''
        UPDATE turnos 
        SET estado = "EN_ATENCION", timestamp_atencion = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (turno['id'],))
    
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True, 
        'turno': dict(turno)
    })

# API para cambiar estado del doctor
@app.route('/api/doctor/cambiar-estado', methods=['POST'])
def cambiar_estado_doctor():
    data = request.json
    doctor_id = data.get('doctor_id')
    estado = data.get('estado')
    
    conn = get_db_connection()
    
    # Convertir estado a valor activo/inactivo
    activo = 1 if estado in ['DISPONIBLE', 'EN_CONSULTA'] else 0
    
    conn.execute('''
        UPDATE doctores 
        SET activo = ?
        WHERE id = ?
    ''', (activo, doctor_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

# API para finalizar consulta
@app.route('/api/doctor/finalizar-consulta', methods=['POST'])
def finalizar_consulta():
    data = request.json
    turno_id = data.get('turno_id')
    destino = data.get('destino')
    vuelve_conmigo = data.get('vuelve_conmigo', False)
    notas = data.get('notas', '')
    
    conn = get_db_connection()
    
    # Mapear destino a estación
    destinos = {
        'FARMACIA': 5,
        'ASESORIA_VISUAL': 6,
        'ESTUDIOS_ESPECIALES': 7,
        'SALIDA': 8
    }
    
    estacion_destino = destinos.get(destino, 8)  # Por defecto salida
    
    # Actualizar turno
    conn.execute('''
        UPDATE turnos 
        SET estado = "FINALIZADO", 
            estacion_actual = ?,
            tiempo_total = CAST((julianday('now') - julianday(timestamp_atencion)) * 24 * 60 AS INTEGER)
        WHERE id = ?
    ''', (estacion_destino, turno_id))
    
    # Registrar en historial
    registrar_historial(turno_id, 'FINALIZADO', 
                       f'Destino: {destino}, Vuelve: {vuelve_conmigo}, Notas: {notas}')
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)