# app.py
from flask import Flask, render_template, jsonify, request
import sqlite3
from estadisticas import registrar_historial, obtener_estadisticas_dia, obtener_estadisticas_mensual
from datetime import datetime

notificaciones_recepcion = []

# Definir NOTIFICACIONES_PREDEFINIDAS globalmente
NOTIFICACIONES_PREDEFINIDAS = {
    'AYUDA_GENERAL': '🆘 Necesito ayuda en consultorio',
    'FALTA_EXPEDIENTE': '📋 Falta expediente del paciente',
    'ERROR_SISTEMA': '🐛 Error en el sistema',
    'MATERIAL_MEDICO': '💊 Necesito material médico',
    'URGENCIA': '🚨 Situación de urgencia',
    'EQUIPO_AVERIADO': '🔧 Equipo médico averiado',
    'LIMPIEZA': '🧹 Necesito servicio de limpieza'
}

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
    
    return jsonify([dict(turno) for turno in turnos])

@app.route('/api/doctores')
def get_doctores():
    conn = get_db_connection()
    doctores = conn.execute('SELECT * FROM doctores WHERE activo = 1 ORDER BY nombre' ).fetchall()
    conn.close()
    return jsonify([dict(d) for d in doctores])

@app.route('/toma-calculos-dashboard')
def toma_calculos_dashboard():
    return render_template('toma_calculos_dashboard.html')

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
            ultimo_numero = int(ultimo_turno['numero'][1:])
            nuevo_numero = f"A{ultimo_numero + 1:03d}"
        else:
            nuevo_numero = "A001"
        
        estacion_inicial = data.get('estacion_inicial', 1)
        doctor_asignado = data.get('doctor_asignado') if estacion_inicial == 4 else None
        
        conn.execute('''
            INSERT INTO turnos (numero, paciente_nombre, paciente_edad, tipo, estacion_actual, doctor_asignado)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (nuevo_numero, data['paciente_nombre'], data['paciente_edad'], data['tipo'], estacion_inicial, doctor_asignado))
        
        turno_id = conn.execute('SELECT last_insert_rowid() as id').fetchone()['id']
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

# APIs de estadísticas
@app.route('/api/estadisticas/dia')
@app.route('/api/estadisticas/dia/<fecha>')
def get_estadisticas_dia(fecha=None):
    try:
        stats = obtener_estadisticas_dia(fecha)
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/estadisticas/mes')
@app.route('/api/estadisticas/mes/<mes>/<anio>')
def get_estadisticas_mes(mes=None, anio=None):
    try:
        mes = int(mes) if mes else None
        anio = int(anio) if anio else None
        stats = obtener_estadisticas_mensual(mes, anio)
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# APIs de doctores
@app.route('/api/doctores/todos')
def get_todos_doctores():
    conn = get_db_connection()
    doctores = conn.execute('SELECT * FROM doctores ORDER BY nombre').fetchall()
    conn.close()
    return jsonify([dict(d) for d in doctores])

@app.route('/api/doctores/nuevo', methods=['POST'])
def agregar_doctor():
    data = request.json
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO doctores (nombre, especialidad, activo, estado_detallado)
        VALUES (?, ?, 0, 'AUSENTE')
    ''', (data['nombre'], data['especialidad']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/doctores/<int:doctor_id>', methods=['DELETE'])
def eliminar_doctor(doctor_id):
    conn = get_db_connection()
    
    turnos_activos = conn.execute('''
        SELECT COUNT(*) as count FROM turnos 
        WHERE doctor_asignado = ? AND estado IN ("PENDIENTE", "EN_ATENCION")
    ''', (doctor_id,)).fetchone()

    if turnos_activos['count'] > 0:
        conn.close()
        return jsonify({
            'success': False, 
            'error': f'No se puede eliminar doctor con {turnos_activos["count"]} turnos activos'
        })
    
    conn.execute('DELETE FROM doctores WHERE id = ?', (doctor_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# Login y dashboard
@app.route('/doctor-login')
def doctor_login_page():
    return render_template('doctor_login.html')

@app.route('/doctor-dashboard')
def doctor_dashboard():
    return render_template('doctor_dashboard.html')

# Ruta para el login de doctores
@app.route('/api/doctor/login', methods=['POST'])
def doctor_login():
    data = request.json
    doctor_id = data.get('doctor_id')
    consultorio_id = data.get('consultorio_id')
    estado = data.get('estado', 'DISPONIBLE')
    
    conn = get_db_connection()
    
    try:
        consultorio = conn.execute(
            'SELECT * FROM consultorios WHERE id = ?', 
            (consultorio_id,)
        ).fetchone()
        
        if not consultorio:
            conn.close()
            return jsonify({'success': False, 'error': 'Consultorio no encontrado'}), 404
            
        if consultorio['ocupado']:
            conn.close()
            return jsonify({'success': False, 'error': 'Este consultorio ya está ocupado'}), 400
        
        # OCUPAR EL CONSULTORIO
        conn.execute('''
            UPDATE consultorios 
            SET ocupado = 1, doctor_actual = ?, timestamp_ocupado = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (doctor_id, consultorio_id))
        
        # Actualizar estado del doctor
        activo = 0 if estado == 'AUSENTE' else 1
        conn.execute('''
            UPDATE doctores 
            SET activo = ?, estado_detallado = ? 
            WHERE id = ?
        ''', (activo, estado, doctor_id))
        
        doctor = conn.execute('SELECT nombre FROM doctores WHERE id = ?', (doctor_id,)).fetchone()
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'doctor_nombre': doctor['nombre'],
            'consultorio_numero': consultorio['numero'],
            'message': 'Sesión iniciada correctamente'
        })
        
    except Exception as e:
        print(f"Error en login doctor: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

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

# API para forzar estado de todos los doctores
@app.route('/api/doctores/forzar-ausentes', methods=['POST'])
def forzar_doctores_ausentes():
    try:
        conn = get_db_connection()
        conn.execute('UPDATE doctores SET activo = 0, estado_detallado = "AUSENTE"')
        count = conn.execute('SELECT changes()').fetchone()[0]
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Se actualizaron {count} doctores a estado AUSENTE'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# API para llamar siguiente paciente
@app.route('/api/doctor/llamar-siguiente', methods=['POST'])
def llamar_siguiente_paciente():
    data = request.json
    doctor_id = data.get('doctor_id')
    
    conn = get_db_connection()
    
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
    
    conn.execute('''
        UPDATE turnos 
        SET estado = "EN_ATENCION", 
            timestamp_atencion = CURRENT_TIMESTAMP,
            estacion_actual = 4
        WHERE id = ?
    ''', (turno['id'],))
    
    registrar_historial(turno['id'], 'EN_ATENCION', f'Doctor: {doctor_id}')
    conn.commit()
    
    turno_actualizado = conn.execute('''
        SELECT t.*, e.nombre as estacion_actual_nombre
        FROM turnos t
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        WHERE t.id = ?
    ''', (turno['id'],)).fetchone()
    
    conn.close()
    return jsonify({'success': True, 'turno': dict(turno_actualizado)})

# API para cambiar estado del doctor
@app.route('/api/doctor/cambiar-estado', methods=['POST'])
def cambiar_estado_doctor():
    data = request.json
    doctor_id = data.get('doctor_id')
    estado = data.get('estado')
    
    conn = get_db_connection()
    
    try:
        if estado == 'DISPONIBLE':
            activo = 1
            disponible = 1
            estado_detallado = 'DISPONIBLE'
        elif estado == 'OCUPADO':
            activo = 1
            disponible = 0
            estado_detallado = 'OCUPADO'
        elif estado == 'AUSENTE':
            activo = 0
            disponible = 0
            estado_detallado = 'AUSENTE'
        else:
            activo = 1
            disponible = 1
            estado_detallado = 'DISPONIBLE'
        
        conn.execute('''
            UPDATE doctores 
            SET activo = ?, disponible = ?, estado_detallado = ?
            WHERE id = ?
        ''', (activo, disponible, estado_detallado, doctor_id))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'estado_actual': estado_detallado})
        
    except Exception as e:
        print(f"Error cambiando estado doctor: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# API para consultorios
@app.route('/api/consultorios')
def get_consultorios():
    conn = get_db_connection()
    consultorios = conn.execute('''
        SELECT c.*, d.nombre as doctor_nombre 
        FROM consultorios c 
        LEFT JOIN doctores d ON c.doctor_actual = d.id 
        ORDER BY c.numero
    ''').fetchall()
    conn.close()
    return jsonify([dict(c) for c in consultorios])

@app.route('/api/consultorios/<int:consultorio_id>/ocupar', methods=['POST'])
def ocupar_consultorio(consultorio_id):
    data = request.json
    doctor_id = data.get('doctor_id')
    
    conn = get_db_connection()
    
    try:
        consultorio = conn.execute(
            'SELECT ocupado FROM consultorios WHERE id = ?', 
            (consultorio_id,)
        ).fetchone()
        
        if consultorio and consultorio['ocupado']:
            conn.close()
            return jsonify({'success': False, 'error': 'Este consultorio ya está ocupado'})
        
        conn.execute('''
            UPDATE consultorios 
            SET ocupado = 1, doctor_actual = ?, timestamp_ocupado = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (doctor_id, consultorio_id))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Consultorio ocupado correctamente'})
        
    except Exception as e:
        print(f"Error ocupando consultorio: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Ruta para logout de doctores
@app.route('/api/doctor/logout', methods=['POST'])
def doctor_logout():
    data = request.json
    doctor_id = data.get('doctor_id')
    
    conn = get_db_connection()
    
    try:
        consultorio = conn.execute(
            'SELECT * FROM consultorios WHERE doctor_actual = ?', 
            (doctor_id,)
        ).fetchone()
        
        if consultorio:
            conn.execute('''
                UPDATE consultorios 
                SET ocupado = 0, doctor_actual = NULL, timestamp_ocupado = NULL
                WHERE doctor_actual = ?
            ''', (doctor_id,))
            print(f"✅ Consultorio {consultorio['numero']} liberado por doctor {doctor_id}")
        
        conn.execute('''
            UPDATE doctores 
            SET activo = 0, estado_detallado = "AUSENTE" 
            WHERE id = ?
        ''', (doctor_id,))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Sesión cerrada y consultorio liberado correctamente'})
        
    except Exception as e:
        print(f"Error en logout doctor: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# SISTEMA DE TURNO VIAJERO 
@app.route('/api/doctor/derivar-paciente', methods=['POST'])
def derivar_paciente():
    data = request.json
    turno_id = data.get('turno_id')
    destino = data.get('destino')
    vuelve_conmigo = data.get('vuelve_conmigo', False)
    notas = data.get('notas', '')
    
    conn = get_db_connection()
    
    try:
        destinos = {
            'TOMA_CALCULOS':3, 
            'TRABAJO_SOCIAL':4,
            'FARMACIA':5,
            'ASESORIA_VISUAL': 6,
            'ESTUDIOS_ESPECIALES': 7,
            'SALIDA': 8
        }
        
        estacion_destino = destinos.get(destino, 8)
        
        # Si vuelve a consulta, crear turno de retorno
        if vuelve_conmigo and destino != 'SALIDA':
            turno_original = conn.execute(
                'SELECT * FROM turnos WHERE id = ?', (turno_id,)
            ).fetchone()
            
            if turno_original:
                nuevo_numero = f"R{turno_original['numero']}"
                
                conn.execute('''
                    INSERT INTO turnos (numero, paciente_nombre, paciente_edad, tipo, 
                                      estacion_actual, doctor_asignado, estado, prioridad)
                    VALUES (?, ?, ?, ?, ?, ?, "PENDIENTE", 2)
                ''', (nuevo_numero, turno_original['paciente_nombre'], 
                      turno_original['paciente_edad'], 'RETORNO_CONSULTA',
                      4, turno_original['doctor_asignado']))
                
                nuevo_turno_id = conn.execute('SELECT last_insert_rowid() as id').fetchone()['id']
                registrar_historial(nuevo_turno_id, 'CREADO', 'Turno de retorno a consulta')
        
        # Actualizar turno actual
        if destino == 'SALIDA':
            conn.execute('''
                UPDATE turnos 
                SET estado = "FINALIZADO", 
                    estacion_actual = ?,
                    tiempo_total = CAST((julianday('now') - julianday(timestamp_atencion)) * 24 * 60 AS INTEGER)
                WHERE id = ?
            ''', (estacion_destino, turno_id))
        else:
            conn.execute('''
                UPDATE turnos 
                SET estado = "EN_PROCESO", 
                    estacion_actual = ?,
                    estacion_siguiente = ?
                WHERE id = ?
            ''', (estacion_destino, 4 if vuelve_conmigo else None, turno_id))
        
        accion = f'DERIVADO_A_{destino}'
        detalles = f'Vuelve: {vuelve_conmigo}, Notas: {notas}'
        registrar_historial(turno_id, accion, detalles)
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Paciente derivado a {destino}',
            'vuelve_conmigo': vuelve_conmigo
        })
        
    except Exception as e:
        print(f"Error derivando paciente: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

        @app.route('/api/turnos/en-transito')
        def get_turnos_en_transito():
            conn = get_db_connection()
            
            turnos = conn.execute('''
                SELECT t.*, 
                    e.nombre as estacion_actual_nombre,
                    d.nombre as doctor_nombre,
                    CAST((julianday('now') - julianday(
                        CASE 
                            WHEN t.timestamp_atencion IS NOT NULL THEN t.timestamp_atencion 
                            ELSE t.timestamp_creacion 
                        END
                    )) * 24 * 60 AS INTEGER) as tiempo_en_estacion,
                    CASE 
                        WHEN t.numero LIKE 'R%' THEN 'RETORNO'
                        ELSE 'NORMAL'
                    END as tipo_turno
                FROM turnos t
                LEFT JOIN estaciones e ON t.estacion_actual = e.id
                LEFT JOIN doctores d ON t.doctor_asignado = d.id
                WHERE t.estado IN ('EN_PROCESO', 'EN_ATENCION')
                OR (t.estado = 'PENDIENTE' AND t.estacion_actual NOT IN (1, 8))
                ORDER BY 
                    CASE WHEN t.estado = 'EN_ATENCION' THEN 1
                        WHEN t.estado = 'EN_PROCESO' THEN 2
                        ELSE 3
                    END,
                    t.timestamp_creacion DESC
            ''').fetchall()
            
            conn.close()
            return jsonify([dict(turno) for turno in turnos])

# Ruta para obtener paciente en atención actual
@app.route('/api/doctor/paciente-actual')
def get_paciente_actual():
    doctor_id = request.args.get('doctor_id')
    
    conn = get_db_connection()
    paciente_actual = conn.execute('''
        SELECT t.*, e.nombre as estacion_actual_nombre
        FROM turnos t
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        WHERE t.doctor_asignado = ? AND t.estado = "EN_ATENCION"
        ORDER BY t.timestamp_atencion DESC
        LIMIT 1
    ''', (doctor_id,)).fetchone()
    conn.close()
    
    if paciente_actual:
        return jsonify({'success': True, 'paciente': dict(paciente_actual)})
    else:
        return jsonify({'success': True, 'paciente': None})

# SISTEMA DE NOTIFICACIONES MEJORADO
@app.route('/api/doctor/notificaciones/predefinidas')
def get_notificaciones_predefinidas():
    return jsonify({
        'success': True,
        'notificaciones': NOTIFICACIONES_PREDEFINIDAS
    })

@app.route('/api/doctor/notificar-recepcion', methods=['POST'])
def notificar_recepcion():
    try:
        data = request.json
        
        required_fields = ['doctor_id', 'doctor_nombre', 'mensaje']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'Campo requerido: {field}'}), 400
        
        notificacion = {
            'id': len(notificaciones_recepcion) + 1,
            'doctor_id': data['doctor_id'],
            'doctor_nombre': data['doctor_nombre'],
            'consultorio': data.get('consultorio', 'No especificado'),
            'mensaje': data['mensaje'],
            'timestamp': datetime.now().isoformat(),
            'leida': False,
            'tipo': data.get('tipo', 'GENERAL')
        }
        
        notificaciones_recepcion.append(notificacion)
        
        if len(notificaciones_recepcion) > 50:
            notificaciones_recepcion.pop(0)
        
        print(f"🔔 NOTIFICACIÓN - Doctor: {data['doctor_nombre']} - {data['mensaje']}")
        
        registrar_historial(0, 'NOTIFICACION_RECEPCION', 
                           f"Doctor: {data['doctor_nombre']} - {data['mensaje']}")
        
        return jsonify({
            'success': True, 
            'message': 'Notificación enviada correctamente',
            'notificacion_id': notificacion['id']
        })
        
    except Exception as e:
        print(f"Error en notificación: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/doctor/notificacion-personalizada', methods=['POST'])
def notificacion_personalizada():
    data = request.json
    
    try:
        required_fields = ['doctor_id', 'doctor_nombre', 'mensaje']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'Campo requerido: {field}'}), 400
        
        notificacion = {
            'id': len(notificaciones_recepcion) + 1,
            'doctor_id': data['doctor_id'],
            'doctor_nombre': data['doctor_nombre'],
            'consultorio': data.get('consultorio', 'No especificado'),
            'mensaje': data['mensaje'],
            'timestamp': datetime.now().isoformat(),
            'leida': False,
            'tipo': 'PERSONALIZADA'
        }
        
        notificaciones_recepcion.append(notificacion)
        
        if len(notificaciones_recepcion) > 50:
            notificaciones_recepcion.pop(0)
        
        print(f"🔔 NOTIFICACIÓN PERSONALIZADA - Doctor: {data['doctor_nombre']} - {data['mensaje']}")
        
        registrar_historial(0, 'NOTIFICACION_PERSONALIZADA', 
                           f"Doctor: {data['doctor_nombre']} - {data['mensaje']}")
        
        return jsonify({'success': True, 'message': 'Notificación enviada correctamente'})
        
    except Exception as e:
        print(f"Error en notificación personalizada: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# APIs para gestión de notificaciones en recepción
@app.route('/api/recepcion/notificaciones')
def obtener_notificaciones_recepcion():
    try:
        notificaciones_ordenadas = sorted(
            [n for n in notificaciones_recepcion if not n['leida']],
            key=lambda x: x['timestamp'],
            reverse=True
        )
        
        notificaciones_leidas = sorted(
            [n for n in notificaciones_recepcion if n['leida']],
            key=lambda x: x['timestamp'],
            reverse=True
        )[:5]
        
        todas_notificaciones = notificaciones_ordenadas + notificaciones_leidas
        
        return jsonify({
            'success': True,
            'notificaciones': todas_notificaciones,
            'total_no_leidas': len(notificaciones_ordenadas)
        })
        
    except Exception as e:
        print(f"Error obteniendo notificaciones: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recepcion/notificaciones/<int:notificacion_id>/leer', methods=['PUT'])
def marcar_notificacion_leida(notificacion_id):
    try:
        for notificacion in notificaciones_recepcion:
            if notificacion['id'] == notificacion_id:
                notificacion['leida'] = True
                return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Notificación no encontrada'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recepcion/notificaciones/limpiar-todas', methods=['DELETE'])
def limpiar_todas_notificaciones():
    try:
        cantidad_eliminadas = len(notificaciones_recepcion)
        notificaciones_recepcion.clear()
        return jsonify({
            'success': True, 
            'message': f'Se limpiaron {cantidad_eliminadas} notificaciones',
            'eliminadas': cantidad_eliminadas
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recepcion/notificaciones/<int:notificacion_id>', methods=['DELETE'])
def eliminar_notificacion(notificacion_id):
    try:
        for i, notificacion in enumerate(notificaciones_recepcion):
            if notificacion['id'] == notificacion_id:
                notificacion_eliminada = notificaciones_recepcion.pop(i)
                return jsonify({'success': True, 'message': 'Notificación eliminada'})
        return jsonify({'success': False, 'error': 'Notificación no encontrada'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    

    # API para obtener turnos en Toma de Cálculos
@app.route('/api/turnos/por-estacion/<int:estacion_id>')
def get_turnos_por_estacion(estacion_id):
    conn = get_db_connection()
    
    turnos = conn.execute('''
        SELECT t.*, 
               e.nombre as estacion_actual_nombre,
               d.nombre as doctor_nombre,
               CAST((julianday('now') - julianday(t.timestamp_creacion)) * 24 * 60 AS INTEGER) as tiempo_espera
        FROM turnos t
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        LEFT JOIN doctores d ON t.doctor_asignado = d.id
        WHERE t.estacion_actual = ? AND t.estado IN ('PENDIENTE', 'EN_PROCESO')
        ORDER BY t.timestamp_creacion ASC
    ''', (estacion_id,)).fetchall()
    
    conn.close()
    return jsonify([dict(turno) for turno in turnos])


@app.route('/api/mediciones/<int:turno_id>')
def get_mediciones_turno(turno_id):
    conn = get_db_connection()
    
    mediciones = conn.execute('''
        SELECT * FROM mediciones_calculos 
        WHERE turno_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
    ''', (turno_id,)).fetchone()
    
    conn.close()
    
    if mediciones:
        return jsonify({'success': True, 'mediciones': dict(mediciones)})
    else:
        return jsonify({'success': True, 'mediciones': None})

#API para finalizar toma de calculos
@app.route('/api/toma-calculos/finalizar', methods=['POST'])
def finalizar_toma_calculos():
    data = request.json
    turno_id = data.get('turno_id')
    mediciones = data.get('mediciones', {})
    observaciones = data.get('observaciones', '')
    atendido_por = data.get('atendido_por', '')
    
    conn = get_db_connection()
    
    try:
        # 1. GUARDAR MEDICiones ESTRUCTURADAS
        conn.execute('''
            INSERT INTO mediciones_calculos 
            (turno_id, agudeza_visual_od, agudeza_visual_oi, presion_intraocular_od, 
             presion_intraocular_oi, queratometria_od, queratometria_oi, 
             refraccion_od, refraccion_oi, observaciones, atendido_por)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            turno_id,
            mediciones.get('agudeza_od'),
            mediciones.get('agudeza_oi'),
            mediciones.get('presion_od'), 
            mediciones.get('presion_oi'),
            mediciones.get('queratometria_od'),
            mediciones.get('queratometria_oi'),
            mediciones.get('refraccion_od'),
            mediciones.get('refraccion_oi'),
            observaciones,
            atendido_por
        ))
        
        # 2. Actualizar el turno para enviarlo a CONSULTA
        conn.execute('''
            UPDATE turnos 
            SET estacion_actual = 4,  -- Consulta Médica
                estado = 'PENDIENTE'
            WHERE id = ?
        ''', (turno_id,))
        
        # 3. Agregar nota resumen a notas_adicionales
        resumen_mediciones = f"\n--- {datetime.now().strftime('%H:%M')} TOMA CÁLCULOS:"
        if mediciones.get('agudeza_od'):
            resumen_mediciones += f"\nAgudeza: {mediciones['agudeza_od']} OD, {mediciones['agudeza_oi']} OI"
        if mediciones.get('presion_od'):
            resumen_mediciones += f"\nPIO: {mediciones['presion_od']} OD, {mediciones['presion_oi']} OI"
        if observaciones:
            resumen_mediciones += f"\nObs: {observaciones}"
        if atendido_por:
            resumen_mediciones += f"\n(Atendido por: {atendido_por})"
            
        # Obtener notas actuales y agregar el resumen
        turno = conn.execute('SELECT notas_adicionales FROM turnos WHERE id = ?', (turno_id,)).fetchone()
        notas_actuales = turno['notas_adicionales'] or ''
        nuevas_notas = notas_actuales + resumen_mediciones
        
        conn.execute('UPDATE turnos SET notas_adicionales = ? WHERE id = ?', (nuevas_notas, turno_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Mediciones guardadas y paciente enviado a consulta'})
        
    except Exception as e:
        print(f"Error finalizando toma de cálculos: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# API para crear turno directo en Toma de Cálculos (para pruebas)
@app.route('/api/toma-calculos/turno-prueba', methods=['POST'])
def crear_turno_prueba_toma_calculos():
    conn = get_db_connection()
    
    try:
        # Crear turno de prueba directamente en Toma de Cálculos
        conn.execute('''
            INSERT INTO turnos (numero, paciente_nombre, paciente_edad, tipo, estado, estacion_actual)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('TC001', 'Paciente Prueba', 35, 'CITA', 'PENDIENTE', 3))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Turno de prueba creado en Toma de Cálculos'})
        
    except Exception as e:
        print(f"Error creando turno prueba: {e}")
        if conn:
            conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)