# app.py - VERSION CORREGIDA
from flask import Flask, render_template, jsonify, request
import sqlite3, json, logging
from estadisticas import registrar_historial, obtener_estadisticas_dia, obtener_estadisticas_mensual
from datetime import datetime
from functools import wraps
from db_utils import get_db_connection

# Se configura el sistema de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Lista en memoria para las notificaciones (se pierde al reiniciar el servidor)
notificaciones_recepcion = []

# Mensajes predefinidos que los doctores pueden enviar a recepcion
NOTIFICACIONES_PREDEFINIDAS = {
    'AYUDA_GENERAL': 'Necesito ayuda en consultorio',
    'FALTA_EXPEDIENTE': 'Falta expediente del paciente',
    'ERROR_SISTEMA': 'Error en el sistema',
    'MATERIAL_MEDICO': 'Necesito material médico',
    'URGENCIA': 'Situación de urgencia',
    'EQUIPO_AVERIADO': 'Equipo médico averiado',
    'LIMPIEZA': 'Necesito servicio de limpieza'
}

app = Flask(__name__)

# Decorador que maneja automaticamente las conexiones a BD
def with_db_connection(f):
    """
    Este decorador se encarga de:
    - Abrir una conexion a la base de datos
    - Pasar la conexion a la funcion
    - Manejar errores automaticamente
    - Cerrar la conexion siempre
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Se abre la conexion y se pasa a la funcion
            with get_db_connection() as conn:
                return f(conn=conn, *args, **kwargs)
        except sqlite3.Error as e:
            # Si hay error de base de datos
            logger.error(f"Error de base de datos en {f.__name__}: {e}")
            return jsonify({'success': False, 'error': f'Error de base de datos: {str(e)}'}), 500
        except Exception as e:
            # Si hay cualquier otro error
            logger.error(f"Error general en {f.__name__}: {e}")
            return jsonify({'success': False, 'error': f'Error interno: {str(e)}'}), 500
    return decorated_function

# ========== RUTAS PRINCIPALES (PAGINAS HTML) ==========

@app.route('/')
def recepcion():
    # Se renderiza la pagina principal de recepcion
    return render_template('recepcion.html')

@app.route('/toma-calculos-dashboard')
def toma_calculos_dashboard():
    # Se renderiza el dashboard para toma de calculos
    return render_template('toma_calculos_dashboard.html')

@app.route('/doctor-login')
def doctor_login_page():
    # Se renderiza la pagina de login para doctores
    return render_template('doctor_login.html')

@app.route('/doctor-dashboard')
def doctor_dashboard():
    # Se renderiza el dashboard principal de doctores
    return render_template('doctor_dashboard.html')

@app.route('/trabajo-social-dashboard')
def trabajo_social_dashboard():
    """Dashboard simple para afiliación de pacientes nuevos"""
    return render_template('trabajo_social_dashboard.html')

# ========== FUNCIONES AUXILIARES ==========

def asignar_a_lista_espera_doctor(conn, turno_id):
    """
    Asigna paciente ya afiliado a la lista de espera de un doctor disponible
    """
    # Buscar doctores activos y disponibles
    doctores = conn.execute('''
        SELECT id, nombre, 
               (SELECT COUNT(*) FROM turnos 
                WHERE doctor_asignado = doctores.id 
                AND estado IN ('PENDIENTE', 'EN_ATENCION')) as pacientes_en_espera
        FROM doctores 
        WHERE activo = 1 AND disponible = 1
        ORDER BY pacientes_en_espera ASC, RANDOM()
        LIMIT 3
    ''').fetchall()
    
    if not doctores:
        return {'asignado': False, 'mensaje': 'No hay doctores disponibles'}
    
    # Seleccionar el doctor con menos pacientes en espera
    doctor = doctores[0]
    
    # Asignar doctor al turno
    conn.execute('''
        UPDATE turnos 
        SET doctor_asignado = ?,
            estado = 'PENDIENTE',
            estacion_actual = 4,  # Consulta Médica
            notas_adicionales = COALESCE(notas_adicionales, '') || ?
        WHERE id = ?
    ''', (
        doctor['id'],
        f"\n--- ASIGNADO A LISTA DE ESPERA ---\n"
        f"Doctor: {doctor['nombre']}\n"
        f"Pacientes en espera del doctor: {doctor['pacientes_en_espera'] + 1}\n"
        f"Fecha asignación: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        turno_id
    ))
    
    # Registrar en historial
    conn.execute('''
        INSERT INTO historial_turnos (turno_id, accion, detalles, usuario)
        VALUES (?, ?, ?, ?)
    ''', (turno_id, 'ASIGNADO_LISTA_ESPERA', 
          f'Doctor: {doctor["nombre"]}, Posición en lista: {doctor["pacientes_en_espera"] + 1}', 
          'sistema'))
    
    return {
        'asignado': True,
        'doctor_id': doctor['id'],
        'doctor_nombre': doctor['nombre'],
        'posicion_lista': doctor['pacientes_en_espera'] + 1
    }

# ========== API PARA MANEJAR TURNOS ==========

@app.route('/api/turnos')
@with_db_connection
def get_turnos(conn):
    # Se obtienen todos los turnos activos (no finalizados ni cancelados)
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
    
    # Se convierten los resultados a diccionarios y se devuelven como JSON
    return jsonify([dict(turno) for turno in turnos])

@app.route('/api/turnos/nuevo', methods=['POST'])
@with_db_connection
def crear_turno(conn):
    # Se obtienen los datos del request
    data = request.json
    
    # Validaciones básicas
    required_fields = ['paciente_nombre', 'paciente_edad', 'tipo']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'success': False, 'error': f'Campo requerido: {field}'}), 400
    
    # Validar que el tipo sea válido
    if data['tipo'] not in ['CITA', 'SIN_CITA']:
        return jsonify({'success': False, 'error': 'Tipo de turno inválido'}), 400
    
    # Se calcula la fecha actual para generar el numero de turno
    fecha_actual = datetime.now().strftime('%Y-%m-%d')
    
    # ===== LÓGICA CORREGIDA DE PRIORIDADES Y DESTINOS =====
    
    # Inicializar variables
    estacion_siguiente = None
    
    # CORRECCIÓN: Para pacientes CON CITA, asumir que YA están afiliados
    if data['tipo'] == 'CITA':
        # Paciente CON CITA - Ya está afiliado por definición
        prioridad = 3  # Prioridad ALTA (con cita)
        prefijo = 'A'   # A = Con Cita
        
        # Determinar destino según selección
        estacion_inicial = data.get('estacion_inicial', 1)
        doctor_asignado = data.get('doctor_asignado') if estacion_inicial == 4 else None
        
        notas_iniciales = f"Tipo: PACIENTE CON CITA\n"
        notas_iniciales += f"Prioridad: {prioridad} (Alta)\n"
        notas_iniciales += f"Destino: {'Consulta Médica' if estacion_inicial == 4 else 'Otra estación'}"
        
        # Para pacientes con cita, estado de afiliación es YA_AFILIADO
        estado_afiliacion = 'YA_AFILIADO'
    
    else:
        # Para pacientes SIN CITA: verificar estado de afiliación
        # CORRECCIÓN: Obtener el estado de afiliación del request
        estado_afiliacion = data.get('estado_afiliacion', 'NO_AFILIADO')
        
        if estado_afiliacion == 'YA_AFILIADO':
            # Paciente YA AFILIADO - va a lista de espera de doctor
            prioridad = 2  # Prioridad MEDIA (ya afiliado)
            prefijo = 'AF'  # AF = Afiliado
            estacion_inicial = 4  # CORRECCIÓN: Va directo a Consulta Médica (estación 4)
            doctor_asignado = None  # Se asignará automáticamente
            
            notas_iniciales = f"Tipo: PACIENTE SIN CITA YA AFILIADO\n"
            notas_iniciales += f"Estado afiliación: YA AFILIADO\n"
            notas_iniciales += f"Prioridad: {prioridad} (Media)\n"
            notas_iniciales += f"Destino: Lista de espera para asignación de doctor"
            
        else:
            # Paciente NO AFILIADO - va a Trabajo Social
            prioridad = 1  # Prioridad BAJA (no afiliado)
            prefijo = 'SC'  # SC = Sin Cita
            estacion_inicial = 2  # Trabajo Social
            doctor_asignado = None
            
            notas_iniciales = f"Tipo: PACIENTE SIN CITA NO AFILIADO\n"
            notas_iniciales += f"Estado afiliación: NO AFILIADO (primera vez)\n"
            notas_iniciales += f"Prioridad: {prioridad} (Baja)\n"
            notas_iniciales += f"Destino: Trabajo Social para afiliación"
    
    # ===== GENERACIÓN DE NÚMERO DE TURNO =====
    
    # Se busca el ultimo turno del dia con el mismo prefijo
    ultimo_turno = conn.execute(
        '''SELECT numero FROM turnos 
           WHERE DATE(timestamp_creacion) = ? 
           AND numero LIKE ? || '%'
           ORDER BY id DESC LIMIT 1''',
        (fecha_actual, prefijo)
    ).fetchone()
    
    # Se genera el nuevo numero de turno según el prefijo
    if ultimo_turno:
        try:
            # Extraer el número después del prefijo
            ultimo_numero = int(ultimo_turno['numero'][len(prefijo):])
            nuevo_numero = f"{prefijo}{ultimo_numero + 1:03d}"
        except ValueError:
            # Si hay error en la conversión, empezar desde 001
            nuevo_numero = f"{prefijo}001"
    else:
        nuevo_numero = f"{prefijo}001"
    
    # ===== INSERTAR EN BASE DE DATOS =====
    
    # Determinar estado inicial
    if data['tipo'] == 'CITA' and doctor_asignado:
        estado = 'PENDIENTE'  # Listo para ser atendido
    elif data['tipo'] == 'SIN_CITA' and estado_afiliacion == 'YA_AFILIADO':
        estado = 'ESPERANDO_ASIGNACION'  # Espera asignación de doctor
    else:
        estado = 'PENDIENTE'
    
    # Se inserta el nuevo turno en la base de datos
    cursor = conn.execute('''
        INSERT INTO turnos 
        (numero, paciente_nombre, paciente_edad, tipo, estacion_actual, estacion_siguiente,
         doctor_asignado, prioridad, estado, notas_adicionales, timestamp_creacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (
        nuevo_numero, 
        data['paciente_nombre'].strip(), 
        data['paciente_edad'], 
        data['tipo'], 
        estacion_inicial, 
        estacion_siguiente,
        doctor_asignado,
        prioridad,
        estado,
        notas_iniciales
    ))
    
    # Se obtiene el ID del turno recien creado
    turno_id = cursor.lastrowid
    
    # ===== PROCESOS ESPECIALES =====
    
    # CORRECCIÓN: Si es paciente sin cita YA AFILIADO, ejecutar asignación automática
    if data['tipo'] == 'SIN_CITA' and estado_afiliacion == 'YA_AFILIADO':
        resultado = asignar_a_lista_espera_doctor(conn, turno_id)
        asignado = resultado.get('asignado', False)
        doctor_nombre = resultado.get('doctor_nombre')
    else:
        asignado = False
        doctor_nombre = None
    
    # Si es paciente con cita y doctor asignado, verificar disponibilidad
    if data['tipo'] == 'CITA' and doctor_asignado and estacion_inicial == 4:
        doctor = conn.execute(
            'SELECT disponible, nombre FROM doctores WHERE id = ?', 
            (doctor_asignado,)
        ).fetchone()
        
        if doctor and doctor['disponible'] == 1:
            # Marcar doctor como ocupado
            conn.execute('''
                UPDATE doctores 
                SET disponible = 0, estado_detallado = 'OCUPADO'
                WHERE id = ?
            ''', (doctor_asignado,))
            doctor_nombre = doctor['nombre']
    
    # ===== REGISTRAR EN HISTORIAL =====
    
    detalles_historial = f'Tipo: {data["tipo"]}, '
    if data['tipo'] == 'SIN_CITA':
        detalles_historial += f'Afiliación: {estado_afiliacion}, '
    detalles_historial += f'Prioridad: {prioridad}, Estación: {estacion_inicial}'
    
    if doctor_asignado or asignado:
        detalles_historial += f', Doctor: {doctor_nombre or "Por asignar"}'
    
    registrar_historial(turno_id, 'CREADO', detalles_historial)
    
    # ===== PREPARAR RESPUESTA =====
    
    respuesta = {
        'success': True, 
        'numero_turno': nuevo_numero, 
        'turno_id': turno_id,
        'tipo': data['tipo'],
        'prioridad': prioridad,
        'estacion_inicial': estacion_inicial,
        'estado': estado,
        'mensaje': f'Turno {nuevo_numero} creado exitosamente'
    }
    
    if data['tipo'] == 'SIN_CITA':
        respuesta['estado_afiliacion'] = estado_afiliacion
        if estado_afiliacion == 'YA_AFILIADO':
            respuesta['asignado_lista_espera'] = asignado
            if asignado:
                respuesta['doctor_asignado'] = doctor_nombre
                respuesta['mensaje'] = f'Turno {nuevo_numero} creado - Agregado a lista de espera del Dr. {doctor_nombre}'
            else:
                respuesta['mensaje'] = f'Turno {nuevo_numero} creado - En espera de asignación de doctor'
    
    elif data['tipo'] == 'CITA' and doctor_asignado:
        respuesta['doctor_asignado'] = doctor_nombre
        respuesta['mensaje'] = f'Turno {nuevo_numero} creado - Cita con Dr. {doctor_nombre}'
    
    return jsonify(respuesta)
@app.route('/api/turnos/pendientes-pago-gabinete')
@with_db_connection
def get_turnos_pendientes_pago(conn):
    # Se obtienen los turnos que estan esperando pago para estudios de gabinete
    turnos = conn.execute('''
        SELECT t.*, 
               d.nombre as doctor_nombre,
               e.nombre as estacion_actual_nombre
        FROM turnos t
        LEFT JOIN doctores d ON t.doctor_asignado = d.id
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        WHERE t.estado = "PENDIENTE_PAGO_ESTUDIOS"
        ORDER BY t.timestamp_creacion ASC
    ''').fetchall()
    
    return jsonify([dict(turno) for turno in turnos])

@app.route('/api/turnos/<int:turno_id>/cancelar', methods=['PUT'])
@with_db_connection
def cancelar_turno(conn, turno_id):
    # Se obtiene la razon de cancelacion del request
    data = request.json
    razon = data.get('razon', 'No especificada') if data else 'No especificada'
    
    # Se actualiza el turno a estado cancelado
    conn.execute('''
        UPDATE turnos 
        SET estado = "CANCELADO", timestamp_cancelado = CURRENT_TIMESTAMP, razon_cancelacion = ?
        WHERE id = ?
    ''', (razon, turno_id))
    
    # Se registra la cancelacion en el historial
    registrar_historial(turno_id, 'CANCELADO', f'Razón: {razon}', 'recepcion')
    
    return jsonify({'success': True})

@app.route('/api/turnos/<int:turno_id>/editar', methods=['PUT'])
@with_db_connection
def editar_turno(conn, turno_id):
    # Se obtienen los nuevos datos del turno
    data = request.json
    
    # Se actualiza la informacion del turno
    conn.execute('''
        UPDATE turnos 
        SET paciente_nombre = ?, paciente_edad = ?, tipo = ?, estacion_actual = ?, doctor_asignado = ?
        WHERE id = ?
    ''', (data['paciente_nombre'], data['paciente_edad'], data['tipo'], data['estacion_actual'], data.get('doctor_asignado'), turno_id))
    
    return jsonify({'success': True})

# ========== API PARA DOCTORES ==========

@app.route('/api/doctores')
@with_db_connection
def get_doctores(conn):
    # Se obtienen todos los doctores activos
    doctores = conn.execute('SELECT * FROM doctores WHERE activo = 1 ORDER BY nombre').fetchall()
    return jsonify([dict(d) for d in doctores])

@app.route('/api/doctores/todos')
@with_db_connection
def get_todos_doctores(conn):
    # Se obtienen todos los doctores (activos e inactivos)
    doctores = conn.execute('SELECT * FROM doctores ORDER BY nombre').fetchall()
    return jsonify([dict(d) for d in doctores])

@app.route('/api/doctores/nuevo', methods=['POST'])
@with_db_connection
def agregar_doctor(conn):
    # Se obtienen los datos del nuevo doctor
    data = request.json
    
    # Se inserta el nuevo doctor en estado inactivo
    conn.execute('''
        INSERT INTO doctores (nombre, especialidad, activo, estado_detallado)
        VALUES (?, ?, 0, 'AUSENTE')
    ''', (data['nombre'], data['especialidad']))
    
    return jsonify({'success': True})

@app.route('/api/doctores/<int:doctor_id>/editar', methods=['PUT'])
@with_db_connection
def editar_doctor(conn, doctor_id):
    # Se obtienen los nuevos datos del doctor
    data = request.json
    nuevo_nombre = data.get('nombre')
    nueva_especialidad = data.get('especialidad')
    
    # Se validan los campos requeridos
    if not nuevo_nombre or not nueva_especialidad:
        return jsonify({'success': False, 'error': 'Nombre y especialidad son requeridos'}), 400
    
    # Se verifica que el doctor exista
    doctor = conn.execute(
        'SELECT id FROM doctores WHERE id = ?', (doctor_id,)
    ).fetchone()
    
    if not doctor:
        return jsonify({'success': False, 'error': 'Doctor no encontrado'}), 404
    
    # Se actualiza la informacion del doctor
    conn.execute('''
        UPDATE doctores 
        SET nombre = ?, especialidad = ?
        WHERE id = ?
    ''', (nuevo_nombre, nueva_especialidad, doctor_id))
    
    return jsonify({'success': True, 'message': 'Doctor actualizado correctamente'})

@app.route('/api/doctores/<int:doctor_id>', methods=['DELETE'])
@with_db_connection
def eliminar_doctor(conn, doctor_id):
    # Se verifica si el doctor tiene turnos activos
    turnos_activos = conn.execute('''
        SELECT COUNT(*) as count FROM turnos 
        WHERE doctor_asignado = ? AND estado IN ("PENDIENTE", "EN_ATENCION")
    ''', (doctor_id,)).fetchone()

    # Si tiene turnos activos, no se puede eliminar
    if turnos_activos['count'] > 0:
        return jsonify({
            'success': False, 
            'error': f'No se puede eliminar doctor con {turnos_activos["count"]} turnos activos'
        })
    
    # Se elimina el doctor
    conn.execute('DELETE FROM doctores WHERE id = ?', (doctor_id,))
    
    return jsonify({'success': True})

# ========== API PARA ESTACIONES ==========

@app.route('/api/estaciones')
@with_db_connection
def get_estaciones_disponibles(conn):
    # Se obtienen todas las estaciones excepto recepcion y salida
    estaciones = conn.execute('SELECT * FROM estaciones WHERE id != 1 AND id != 8').fetchall()
    return jsonify([dict(e) for e in estaciones])

# ========== API PARA ESTADISTICAS ==========

@app.route('/api/estadisticas/dia')
@app.route('/api/estadisticas/dia/<fecha>')
def get_estadisticas_dia(fecha=None):
    try:
        # Se obtienen las estadisticas del dia
        stats = obtener_estadisticas_dia(fecha)
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/estadisticas/mes')
@app.route('/api/estadisticas/mes/<mes>/<anio>')
def get_estadisticas_mes(mes=None, anio=None):
    try:
        # Se convierten los parametros a enteros si existen
        mes = int(mes) if mes else None
        anio = int(anio) if anio else None
        
        # Se obtienen las estadisticas del mes
        stats = obtener_estadisticas_mensual(mes, anio)
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== API PARA ESTUDIOS DE GABINETE ==========

@app.route('/api/turnos/<int:turno_id>/derivar-estudios', methods=['POST'])
@with_db_connection
def derivar_estudios(conn, turno_id):
    logger.info(f"Derivando turno {turno_id} a estudios")
    
    # Se obtienen los datos del request
    data = request.get_json()
    
    if not data:
        return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400
    
    # Se procesan los estudios solicitados
    estudios = data.get('estudios', ['Agudeza Visual', 'Presion Intraocular'])
    estudios_json = json.dumps(estudios)
    
    # Se verifica que el turno exista
    turno_existente = conn.execute(
        'SELECT id, paciente_nombre FROM turnos WHERE id = ?', 
        (turno_id,)
    ).fetchone()
    
    if not turno_existente:
        return jsonify({'success': False, 'error': 'Turno no encontrado'}), 404
    
    # Se actualiza el turno para derivarlo a estudios
    conn.execute('''
        UPDATE turnos 
        SET estado = "PENDIENTE_PAGO_ESTUDIOS",
            estacion_actual = 1,
            estudios_solicitados = ?,
            necesita_retorno = 1
        WHERE id = ?
    ''', (estudios_json, turno_id))
    
    # Se registra en el historial
    conn.execute('''
        INSERT INTO historial_turnos (turno_id, accion, detalles, usuario)
        VALUES (?, ?, ?, ?)
    ''', (turno_id, 'DERIVADO_ESTUDIOS', f"Estudios: {estudios}", 'doctor'))
    
    return jsonify({
        'success': True, 
        'message': 'Paciente derivado exitosamente a gabinete'
    })

@app.route('/api/turnos/<int:turno_id>/pagar-estudios', methods=['POST'])
@with_db_connection
def pagar_estudios(conn, turno_id):
    logger.info(f"Procesando pago para turno {turno_id}")
    
    # Se verifica que el turno exista
    turno = conn.execute('SELECT * FROM turnos WHERE id = ?', (turno_id,)).fetchone()
    if not turno:
        logger.info(f"Turno {turno_id} no encontrado")
        return jsonify({'success': False, 'error': 'Turno no encontrado'}), 404
        
    logger.info(f"Turno encontrado - Estado actual: {turno['estado']}, Estación: {turno['estacion_actual']}")
    
    # Se actualiza el turno a estado "en estudios"
    conn.execute('''
        UPDATE turnos 
        SET estado = "EN_ESTUDIOS",
            estacion_actual = 3
        WHERE id = ?
    ''', (turno_id,))
    
    # Se registra en el historial
    conn.execute('''
        INSERT INTO historial_turnos (turno_id, accion, detalles, usuario)
        VALUES (?, ?, ?, ?)
    ''', (turno_id, 'ESTUDIOS_CONFIRMADOS', 'Estudios confirmados y enviado a Gabinete', 'recepcion'))
    
    logger.info(f"Turno {turno_id} actualizado exitosamente a EN_ESTUDIOS")
    
    return jsonify({
        'success': True, 
        'message': 'Estudios confirmados y paciente enviado a Gabinete'
    })

# ========== API PARA TOMA DE CALCULOS ==========

@app.route('/api/turnos/<int:turno_id>/actualizar-estudios', methods=['POST'])
@with_db_connection
def actualizar_estudios_turno(conn, turno_id):
    # Se obtienen los estudios seleccionados
    data = request.json
    estudios = data.get('estudios', [])
    
    # Se actualizan los estudios solicitados en el turno
    conn.execute('''
        UPDATE turnos 
        SET estudios_solicitados = ?
        WHERE id = ?
    ''', (json.dumps(estudios), turno_id))
    
    # Se registra en el historial
    conn.execute('''
        INSERT INTO historial_turnos (turno_id, accion, detalles, usuario)
        VALUES (?, ?, ?, ?)
    ''', (turno_id, 'ESTUDIOS_SELECCIONADOS', f"Estudios confirmados: {estudios}", 'recepcion'))
    
    return jsonify({'success': True, 'message': 'Estudios actualizados correctamente'})

@app.route('/api/mediciones/<int:turno_id>')
@with_db_connection
def get_mediciones_turno(conn, turno_id):
    # Se obtienen las mediciones mas recientes del turno
    mediciones = conn.execute('''
        SELECT * FROM mediciones_calculos 
        WHERE turno_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
    ''', (turno_id,)).fetchone()
    
    if mediciones:
        return jsonify({'success': True, 'mediciones': dict(mediciones)})
    else:
        return jsonify({'success': True, 'mediciones': None})

@app.route('/api/toma-calculos/finalizar', methods=['POST'])
@with_db_connection
def finalizar_toma_calculos(conn):
    # Se obtienen los datos de finalizacion
    data = request.json
    turno_id = data.get('turno_id')
    observaciones = data.get('observaciones', 'Estudios completados')
    atendido_por = data.get('atendido_por', 'Toma de Cálculos')
    
    logger.info(f"Finalizando estudios para turno {turno_id}")
    
    # Se verifica que el turno exista
    turno = conn.execute('SELECT * FROM turnos WHERE id = ?', (turno_id,)).fetchone()
    if not turno:
        return jsonify({'success': False, 'error': 'Turno no encontrado'}), 404
        
    logger.info(f"Turno encontrado - {turno['numero']}")

    # Se actualiza el turno para enviarlo a consulta medica
    conn.execute('''
        UPDATE turnos 
        SET estacion_actual = 4,
            estado = 'PENDIENTE'
        WHERE id = ?
    ''', (turno_id,))
    
    logger.info("Turno actualizado a Consulta Médica")

    # Se preparan las notas adicionales
    resumen = f"\n--- {datetime.now().strftime('%H:%M')} ESTUDIOS COMPLETADOS ---\n{observaciones}"
    if atendido_por:
        resumen += f"\nAtendido por: {atendido_por}"
        
    # Se actualizan las notas del turno
    turno_actual = conn.execute('SELECT notas_adicionales FROM turnos WHERE id = ?', (turno_id,)).fetchone()
    notas_actuales = turno_actual['notas_adicionales'] or ''
    nuevas_notas = notas_actuales + resumen
    
    conn.execute('UPDATE turnos SET notas_adicionales = ? WHERE id = ?', (nuevas_notas, turno_id))
    
    # Se registra en el historial
    conn.execute('''
        INSERT INTO historial_turnos (turno_id, accion, detalles, usuario)
        VALUES (?, ?, ?, ?)
    ''', (turno_id, 'ESTUDIOS_COMPLETADOS', 'Estudios de gabinete completados - Enviado a consulta', 'toma_calculos'))
    
    logger.info("Estudios finalizados exitosamente")
    
    return jsonify({
        'success': True, 
        'message': 'Estudios completados - Paciente enviado a consulta'
    })

# ========== API PARA ENFERMEROS ==========

@app.route('/api/enfermeros')
@with_db_connection
def get_enfermeros(conn):
    # Se obtienen todos los enfermeros
    enfermeros = conn.execute('SELECT * FROM enfermeros ORDER BY nombre').fetchall()
    return jsonify([dict(enfermero) for enfermero in enfermeros])

@app.route('/api/enfermeros/nuevo', methods=['POST'])
@with_db_connection
def agregar_enfermero(conn):
    # Se obtienen los datos del nuevo enfermero
    data = request.json
    conn.execute('INSERT INTO enfermeros (nombre) VALUES (?)', (data['nombre'],))
    return jsonify({'success': True})

@app.route('/api/enfermeros/<int:enfermero_id>/editar', methods=['PUT'])
@with_db_connection
def editar_enfermero(conn, enfermero_id):
    # Se obtienen los nuevos datos del enfermero
    data = request.json
    nuevo_nombre = data.get('nombre')
    
    if not nuevo_nombre:
        return jsonify({'success': False, 'error': 'Nombre requerido'}), 400
    
    # Se verifica que el enfermero exista
    enfermero = conn.execute(
        'SELECT id FROM enfermeros WHERE id = ?', (enfermero_id,)
    ).fetchone()
    
    if not enfermero:
        return jsonify({'success': False, 'error': 'Enfermero no encontrado'}), 404
    
    # Se actualiza el nombre del enfermero
    conn.execute('UPDATE enfermeros SET nombre = ? WHERE id = ?', (nuevo_nombre, enfermero_id))
    return jsonify({'success': True})

@app.route('/api/enfermeros/<int:enfermero_id>', methods=['DELETE'])
@with_db_connection
def eliminar_enfermero(conn, enfermero_id):
    # Se verifica que el enfermero exista y no este activo
    enfermero = conn.execute(
        'SELECT activo FROM enfermeros WHERE id = ?', (enfermero_id,)
    ).fetchone()
    
    if not enfermero:
        return jsonify({'success': False, 'error': 'Enfermero no encontrado'}), 404
        
    if enfermero['activo'] == 1:
        return jsonify({
            'success': False, 
            'error': 'No se puede eliminar un enfermero activo. Desactívalo primero.'
        })
    
    # Se elimina el enfermero
    conn.execute('DELETE FROM enfermeros WHERE id = ?', (enfermero_id,))
    return jsonify({'success': True})

@app.route('/api/enfermeros/<int:enfermero_id>/toggle-activo', methods=['POST'])
@with_db_connection
def toggle_activo_enfermero(conn, enfermero_id):
    # Se verifica que el enfermero exista
    enfermero = conn.execute(
        'SELECT activo FROM enfermeros WHERE id = ?', (enfermero_id,)
    ).fetchone()
    
    if not enfermero:
        return jsonify({'success': False, 'error': 'Enfermero no encontrado'}), 404
    
    # Se cambia el estado activo/inactivo
    nuevo_estado = 0 if enfermero['activo'] == 1 else 1
        
    conn.execute('UPDATE enfermeros SET activo = ? WHERE id = ?', (nuevo_estado, enfermero_id))
    return jsonify({'success': True, 'nuevo_estado': nuevo_estado})

@app.route('/api/enfermeros/activos')
@with_db_connection
def get_enfermeros_activos(conn):
    # Se obtienen solo los enfermeros activos
    enfermeros = conn.execute('SELECT * FROM enfermeros WHERE activo = 1 ORDER BY nombre').fetchall()
    return jsonify([dict(enfermero) for enfermero in enfermeros])

# ========== API PARA DOCTORES (LOGIN Y DASHBOARD) ==========

@app.route('/api/doctor/login', methods=['POST'])
@with_db_connection
def doctor_login(conn):
    # Se obtienen los datos de login
    data = request.json
    doctor_id = data.get('doctor_id')
    consultorio_id = data.get('consultorio_id')
    estado = data.get('estado', 'DISPONIBLE')
    
    # Se verifica que el consultorio exista
    consultorio = conn.execute(
        'SELECT * FROM consultorios WHERE id = ?', 
        (consultorio_id,)
    ).fetchone()
    
    if not consultorio:
        return jsonify({'success': False, 'error': 'Consultorio no encontrado'}), 404
        
    # Se verifica que el consultorio no este ocupado
    if consultorio['ocupado']:
        return jsonify({'success': False, 'error': 'Este consultorio ya está ocupado'}), 400
    
    # Se ocupa el consultorio con el doctor
    conn.execute('''
        UPDATE consultorios 
        SET ocupado = 1, doctor_actual = ?, timestamp_ocupado = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (doctor_id, consultorio_id))
    
    # Se actualiza el estado del doctor
    activo = 0 if estado == 'AUSENTE' else 1
    conn.execute('''
        UPDATE doctores 
        SET activo = ?, estado_detallado = ? 
        WHERE id = ?
    ''', (activo, estado, doctor_id))
    
    # Se obtiene el nombre del doctor para la respuesta
    doctor = conn.execute('SELECT nombre FROM doctores WHERE id = ?', (doctor_id,)).fetchone()
    
    return jsonify({
        'success': True, 
        'doctor_nombre': doctor['nombre'],
        'consultorio_numero': consultorio['numero'],
        'message': 'Sesión iniciada correctamente'
    })

@app.route('/api/doctor/turnos')
@with_db_connection
def get_turnos_doctor(conn):
    # Se obtiene el ID del doctor de los parametros de la URL
    doctor_id = request.args.get('doctor_id')
    
    # Se obtienen los turnos pendientes del doctor
    turnos = conn.execute('''
        SELECT t.*, e.nombre as estacion_actual_nombre
        FROM turnos t
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        WHERE t.doctor_asignado = ? AND t.estado = "PENDIENTE"
        ORDER BY t.timestamp_creacion ASC
    ''', (doctor_id,)).fetchall()
    
    return jsonify([dict(turno) for turno in turnos])

@app.route('/api/doctor/llamar-siguiente', methods=['POST'])
@with_db_connection
def llamar_siguiente_paciente(conn):
    # Se obtiene el ID del doctor
    data = request.json
    doctor_id = data.get('doctor_id')
    
    # Se busca el siguiente paciente en espera del doctor
    turno = conn.execute('''
        SELECT t.*, e.nombre as estacion_actual_nombre
        FROM turnos t
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        WHERE t.doctor_asignado = ? AND t.estado = "PENDIENTE"
        ORDER BY t.timestamp_creacion ASC
        LIMIT 1
    ''', (doctor_id,)).fetchone()
    
    # Si no hay pacientes en espera, se devuelve error
    if not turno:
        return jsonify({'success': False, 'error': 'No hay pacientes en espera'})
    
    # Se actualiza el turno a estado "en atencion"
    conn.execute('''
        UPDATE turnos 
        SET estado = "EN_ATENCION", 
            timestamp_atencion = CURRENT_TIMESTAMP,
            estacion_actual = 4
        WHERE id = ?
    ''', (turno['id'],))
    
    # Se registra en el historial
    registrar_historial(turno['id'], 'EN_ATENCION', f'Doctor: {doctor_id}')
    
    # Se obtiene el turno actualizado para devolverlo
    turno_actualizado = conn.execute('''
        SELECT t.*, e.nombre as estacion_actual_nombre
        FROM turnos t
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        WHERE t.id = ?
    ''', (turno['id'],)).fetchone()
    
    return jsonify({'success': True, 'turno': dict(turno_actualizado)})

@app.route('/api/doctor/cambiar-estado', methods=['POST'])
@with_db_connection
def cambiar_estado_doctor(conn):
    # Se obtienen los datos para cambiar estado
    data = request.json
    doctor_id = data.get('doctor_id')
    estado = data.get('estado')
    
    # Se determina el estado detallado segun la opcion seleccionada
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
    
    # Se actualiza el estado del doctor
    conn.execute('''
        UPDATE doctores 
        SET activo = ?, disponible = ?, estado_detallado = ?
        WHERE id = ?
    ''', (activo, disponible, estado_detallado, doctor_id))
    
    return jsonify({'success': True, 'estado_actual': estado_detallado})

@app.route('/api/doctor/logout', methods=['POST'])
@with_db_connection
def doctor_logout(conn):
    # Se obtiene el ID del doctor que quiere cerrar sesion
    data = request.json
    doctor_id = data.get('doctor_id')
    
    # Se busca el consultorio que esta ocupando el doctor
    consultorio = conn.execute(
        'SELECT * FROM consultorios WHERE doctor_actual = ?', 
        (doctor_id,)
    ).fetchone()
    
    # Si el doctor tiene consultorio ocupado, se libera
    if consultorio:
        conn.execute('''
            UPDATE consultorios 
            SET ocupado = 0, doctor_actual = NULL, timestamp_ocupado = NULL
            WHERE doctor_actual = ?
        ''', (doctor_id,))
        logger.info(f"Consultorio {consultorio['numero']} liberado por doctor {doctor_id}")
    
    # Se actualiza el estado del doctor a ausente
    conn.execute('''
        UPDATE doctores 
        SET activo = 0, estado_detallado = "AUSENTE" 
        WHERE id = ?
    ''', (doctor_id,))
    
    return jsonify({'success': True, 'message': 'Sesión cerrada y consultorio liberado correctamente'})

# ========== API PARA CONSULTORIOS ==========

@app.route('/api/consultorios')
@with_db_connection
def get_consultorios(conn):
    # Se obtienen todos los consultorios con informacion del doctor asignado
    consultorios = conn.execute('''
        SELECT c.*, d.nombre as doctor_nombre 
        FROM consultorios c 
        LEFT JOIN doctores d ON c.doctor_actual = d.id 
        ORDER BY c.numero
    ''').fetchall()
    return jsonify([dict(c) for c in consultorios])

@app.route('/api/consultorios/<int:consultorio_id>/ocupar', methods=['POST'])
@with_db_connection
def ocupar_consultorio(conn, consultorio_id):
    # Se obtiene el ID del doctor que quiere ocupar el consultorio
    data = request.json
    doctor_id = data.get('doctor_id')
    
    # Se verifica que el consultorio no este ocupado
    consultorio = conn.execute(
        'SELECT ocupado FROM consultorios WHERE id = ?', 
        (consultorio_id,)
    ).fetchone()
    
    if consultorio and consultorio['ocupado']:
        return jsonify({'success': False, 'error': 'Este consultorio ya está ocupado'})
    
    # Se ocupa el consultorio con el doctor
    conn.execute('''
        UPDATE consultorios 
        SET ocupado = 1, doctor_actual = ?, timestamp_ocupado = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (doctor_id, consultorio_id))
    
    return jsonify({'success': True, 'message': 'Consultorio ocupado correctamente'})

# ========== API PARA DERIVAR PACIENTES ==========

@app.route('/api/doctor/derivar-paciente', methods=['POST'])
@with_db_connection
def derivar_paciente(conn):
    # Se obtienen los datos de derivacion
    data = request.json
    turno_id = data.get('turno_id')
    destino = data.get('destino')
    vuelve_conmigo = data.get('vuelve_conmigo', False)
    notas = data.get('notas', '')
    
    # Mapeo de destinos a IDs de estacion
    destinos = {
        'TOMA_CALCULOS':3, 
        'TRABAJO_SOCIAL':2,
        'FARMACIA':5,
        'ASESORIA_VISUAL': 6,
        'SALIDA': 7
    }
    
    estacion_destino = destinos.get(destino, 8)
    
    # Si el paciente debe volver, se crea un turno de retorno
    if vuelve_conmigo and destino != 'SALIDA':
        turno_original = conn.execute(
            'SELECT * FROM turnos WHERE id = ?', (turno_id,)
        ).fetchone()
        
        if turno_original:
            # Se genera un numero de turno de retorno
            nuevo_numero = f"R{turno_original['numero']}"
            
            # Se crea el turno de retorno
            conn.execute('''
                INSERT INTO turnos (numero, paciente_nombre, paciente_edad, tipo, 
                                  estacion_actual, doctor_asignado, estado, prioridad)
                VALUES (?, ?, ?, ?, ?, ?, "PENDIENTE", 2)
            ''', (nuevo_numero, turno_original['paciente_nombre'], 
                  turno_original['paciente_edad'], 'RETORNO_CONSULTA',
                  4, turno_original['doctor_asignado']))
            
            # Se obtiene el ID del nuevo turno y se registra en historial
            nuevo_turno_id = conn.execute('SELECT last_insert_rowid() as id').fetchone()['id']
            registrar_historial(nuevo_turno_id, 'CREADO', 'Turno de retorno a consulta')
    
    # Se actualiza el turno original segun el destino
    if destino == 'SALIDA':
        # Si va a salida, se finaliza el turno
        conn.execute('''
            UPDATE turnos 
            SET estado = "FINALIZADO", 
                estacion_actual = ?,
                tiempo_total = CAST((julianday('now') - julianday(timestamp_atencion)) * 24 * 60 AS INTEGER)
            WHERE id = ?
        ''', (estacion_destino, turno_id))
    else:
        # Si va a otra estacion, se marca como en proceso
        conn.execute('''
            UPDATE turnos 
            SET estado = "EN_PROCESO", 
                estacion_actual = ?,
                estacion_siguiente = ?
            WHERE id = ?
        ''', (estacion_destino, 4 if vuelve_conmigo else None, turno_id))
    
    # Se registra la derivacion en el historial
    accion = f'DERIVADO_A_{destino}'
    detalles = f'Vuelve: {vuelve_conmigo}, Notas: {notas}'
    registrar_historial(turno_id, accion, detalles)
    
    return jsonify({
        'success': True, 
        'message': f'Paciente derivado a {destino}',
        'vuelve_conmigo': vuelve_conmigo
    })

@app.route('/api/doctor/paciente-actual')
@with_db_connection
def get_paciente_actual(conn):
    # Se obtiene el ID del doctor de los parametros de la URL
    doctor_id = request.args.get('doctor_id')
    
    # Se busca el paciente que esta actualmente en atencion con el doctor
    paciente_actual = conn.execute('''
        SELECT t.*, e.nombre as estacion_actual_nombre
        FROM turnos t
        LEFT JOIN estaciones e ON t.estacion_actual = e.id
        WHERE t.doctor_asignado = ? AND t.estado = "EN_ATENCION"
        ORDER BY t.timestamp_atencion DESC
        LIMIT 1
    ''', (doctor_id,)).fetchone()
    
    if paciente_actual:
        return jsonify({'success': True, 'paciente': dict(paciente_actual)})
    else:
        return jsonify({'success': True, 'paciente': None})

# ========== API PARA NOTIFICACIONES ==========

@app.route('/api/doctor/notificaciones/predefinidas')
def get_notificaciones_predefinidas():
    # Se devuelven las notificaciones predefinidas disponibles
    return jsonify({
        'success': True,
        'notificaciones': NOTIFICACIONES_PREDEFINIDAS
    })

@app.route('/api/doctor/notificar-recepcion', methods=['POST'])
def notificar_recepcion():
    try:
        # Se obtienen los datos de la notificacion
        data = request.json
        
        # Se validan los campos requeridos
        required_fields = ['doctor_id', 'doctor_nombre', 'mensaje']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'error': f'Campo requerido: {field}'}), 400
        
        # Se crea la notificacion
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
        
        # Se agrega a la lista de notificaciones
        notificaciones_recepcion.append(notificacion)
        
        # Se mantiene un maximo de 50 notificaciones en memoria
        if len(notificaciones_recepcion) > 50:
            notificaciones_recepcion.pop(0)
        
        logger.info(f"NOTIFICACION - Doctor: {data['doctor_nombre']} - {data['mensaje']}")
        
        # Se registra en el historial del sistema
        registrar_historial(0, 'NOTIFICACION_RECEPCION', 
                           f"Doctor: {data['doctor_nombre']} - {data['mensaje']}")
        
        return jsonify({
            'success': True, 
            'message': 'Notificación enviada correctamente',
            'notificacion_id': notificacion['id']
        })
        
    except Exception as e:
        logger.error(f"Error en notificación: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/doctor/notificacion-personalizada', methods=['POST'])
def notificacion_personalizada():
    # Similar a notificar_recepcion pero para mensajes personalizados
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
        
        logger.info(f"NOTIFICACION PERSONALIZADA - Doctor: {data['doctor_nombre']} - {data['mensaje']}")
        
        registrar_historial(0, 'NOTIFICACION_PERSONALIZADA', 
                           f"Doctor: {data['doctor_nombre']} - {data['mensaje']}")
        
        return jsonify({'success': True, 'message': 'Notificación enviada correctamente'})
        
    except Exception as e:
        logger.error(f"Error en notificación personalizada: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== API PARA GESTION DE NOTIFICACIONES EN RECEPCION ==========

@app.route('/api/recepcion/notificaciones')
def obtener_notificaciones_recepcion():
    try:
        # Se obtienen las notificaciones no leidas, ordenadas por fecha (mas recientes primero)
        notificaciones_ordenadas = sorted(
            [n for n in notificaciones_recepcion if not n['leida']],
            key=lambda x: x['timestamp'],
            reverse=True
        )
        
        # Se obtienen las ultimas 5 notificaciones leidas
        notificaciones_leidas = sorted(
            [n for n in notificaciones_recepcion if n['leida']],
            key=lambda x: x['timestamp'],
            reverse=True
        )[:5]
        
        # Se combinan ambas listas
        todas_notificaciones = notificaciones_ordenadas + notificaciones_leidas
        
        return jsonify({
            'success': True,
            'notificaciones': todas_notificaciones,
            'total_no_leidas': len(notificaciones_ordenadas)
        })
        
    except Exception as e:
        logger.error(f"Error obteniendo notificaciones: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recepcion/notificaciones/<int:notificacion_id>/leer', methods=['PUT'])
def marcar_notificacion_leida(notificacion_id):
    try:
        # Se busca la notificacion por ID y se marca como leida
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
        # Se cuenta cuantas notificaciones se van a eliminar
        cantidad_eliminadas = len(notificaciones_recepcion)
        
        # Se limpia toda la lista de notificaciones
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
        # Se busca la notificacion por ID y se elimina
        for i, notificacion in enumerate(notificaciones_recepcion):
            if notificacion['id'] == notificacion_id:
                notificacion_eliminada = notificaciones_recepcion.pop(i)
                return jsonify({'success': True, 'message': 'Notificación eliminada'})
        return jsonify({'success': False, 'error': 'Notificación no encontrada'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== API PARA TURNOS POR ESTACION ==========

@app.route('/api/turnos/por-estacion/<int:estacion_id>')
@with_db_connection
def get_turnos_por_estacion(conn, estacion_id):
    try:
        # Para Toma de Calculos (estacion 3) se buscan turnos con estado 'EN_ESTUDIOS'
        if estacion_id == 3:
            turnos = conn.execute('''
                SELECT t.*, 
                       e.nombre as estacion_actual_nombre,
                       d.nombre as doctor_nombre,
                       CAST((julianday('now') - julianday(t.timestamp_creacion)) * 24 * 60 AS INTEGER) as tiempo_espera,
                       t.estudios_solicitados
                FROM turnos t
                LEFT JOIN estaciones e ON t.estacion_actual = e.id
                LEFT JOIN doctores d ON t.doctor_asignado = d.id
                WHERE t.estacion_actual = ? AND t.estado = 'EN_ESTUDIOS'
                ORDER BY t.timestamp_creacion ASC
            ''', (estacion_id,)).fetchall()
        else:
            # Para otras estaciones, se buscan turnos pendientes o en proceso
            turnos = conn.execute('''
                SELECT t.*, 
                       e.nombre as estacion_actual_nombre,
                       d.nombre as doctor_nombre,
                       CAST((julianday('now') - julianday(t.timestamp_creacion)) * 24 * 60 AS INTEGER) as tiempo_espera,
                       t.estudios_solicitados
                FROM turnos t
                LEFT JOIN estaciones e ON t.estacion_actual = e.id
                LEFT JOIN doctores d ON t.doctor_asignado = d.id
                WHERE t.estacion_actual = ? AND t.estado IN ('PENDIENTE', 'EN_PROCESO')
                ORDER BY t.timestamp_creacion ASC
            ''', (estacion_id,)).fetchall()
        
        logger.info(f"Turnos encontrados para estación {estacion_id}: {len(turnos)}")
        return jsonify([dict(turno) for turno in turnos])
        
    except Exception as e:
        logger.error(f"Error en get_turnos_por_estacion: {e}")
        return jsonify({'error': str(e)}), 500

# ========== API PARA TURNOS EN TRANSITO ==========

@app.route('/api/turnos/en-transito')
@with_db_connection
def get_turnos_en_transito(conn):
    try:
        # Se obtienen todos los turnos que estan en proceso (no en recepcion ni salida)
        turnos = conn.execute('''
            SELECT t.*, 
                   e.nombre as estacion_actual_nombre,
                   d.nombre as doctor_nombre,
                   CAST((julianday('now') - julianday(t.timestamp_creacion)) * 24 * 60 AS INTEGER) as tiempo_espera,
                   CASE 
                       WHEN t.numero LIKE 'R%' THEN 'RETORNO'
                       WHEN t.estado = 'PENDIENTE_PAGO_ESTUDIOS' THEN 'ESPERANDO_PAGO'
                       WHEN t.estado = 'EN_ESTUDIOS' THEN 'EN_GABINETE'
                       WHEN t.necesita_retorno = 1 THEN 'CON_RETORNO'
                       ELSE 'NORMAL'
                   END as tipo_turno,
                   t.necesita_retorno,
                   t.estudios_solicitados
            FROM turnos t
            LEFT JOIN estaciones e ON t.estacion_actual = e.id
            LEFT JOIN doctores d ON t.doctor_asignado = d.id
            WHERE t.estado IN ('EN_PROCESO', 'EN_ATENCION', 'PENDIENTE_PAGO_ESTUDIOS', 'EN_ESTUDIOS', 'EN_RETORNO_CONSULTA')
               OR (t.estado = 'PENDIENTE' AND t.estacion_actual NOT IN (1, 8))
            ORDER BY 
                CASE 
                    WHEN t.estado = 'EN_ATENCION' THEN 1
                    WHEN t.estado = 'EN_RETORNO_CONSULTA' THEN 2
                    WHEN t.estado = 'PENDIENTE_PAGO_ESTUDIOS' THEN 3
                    WHEN t.estado = 'EN_ESTUDIOS' THEN 4
                    WHEN t.estado = 'EN_PROCESO' THEN 5
                    ELSE 6
                END,
                t.prioridad DESC,
                t.timestamp_creacion ASC
        ''').fetchall()
        
        return jsonify([dict(turno) for turno in turnos])
        
    except Exception as e:
        logger.error(f"Error en turnos en tránsito: {e}")
        return jsonify({'error': str(e)}), 500

# ========== API PARA TRABAJO SOCIAL ==========

@app.route('/api/trabajo-social/pacientes')
@with_db_connection
def get_pacientes_para_afiliacion(conn):
    """Obtiene pacientes nuevos que necesitan ser afiliados"""
    
    pacientes = conn.execute('''
        SELECT 
            t.*,
            CAST((julianday('now') - julianday(t.timestamp_creacion)) * 24 * 60 AS INTEGER) as tiempo_espera
        FROM turnos t
        WHERE t.estacion_actual = 2  -- Trabajo Social
          AND t.tipo = 'SIN_CITA'    -- Pacientes sin cita
          AND t.estado = 'PENDIENTE' -- Pendientes de afiliación
          AND t.notas_adicionales NOT LIKE '%AFILIADO%'
        ORDER BY t.timestamp_creacion ASC
    ''').fetchall()
    
    return jsonify({
        'success': True,
        'pacientes': [dict(p) for p in pacientes]
    })

@app.route('/api/trabajo-social/pacientes/<int:turno_id>/afiliar', methods=['POST'])
@with_db_connection
def afiliar_paciente(conn, turno_id):
    """Marca paciente como afiliado y lo deja esperando asignación de doctor"""
    
    # Verificar que el turno existe
    turno = conn.execute(
        'SELECT * FROM turnos WHERE id = ? AND estacion_actual = 2',
        (turno_id,)
    ).fetchone()
    
    if not turno:
        return jsonify({'success': False, 'error': 'Paciente no encontrado en Trabajo Social'}), 404
    
    # Agregar notas de afiliación
    notas_actuales = turno['notas_adicionales'] or ''
    nueva_nota = f"\n--- PACIENTE AFILIADO ---\n"
    nueva_nota += f"Fecha de afiliación: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    nueva_nota += f"Proceso: Afiliación completada en Trabajo Social\n"
    nueva_nota += f"Estado: Esperando asignación de doctor"
    
    # Actualizar el turno:
    # 1. Mantener en Trabajo Social (estación 2) pero cambiar estado
    # 2. Agregar notas de afiliación
    # 3. Cambiar estado a 'ESPERANDO_DOCTOR' o similar
    # 4. Prioridad: 1 (normal)
    
    conn.execute('''
        UPDATE turnos 
        SET estado = 'ESPERANDO_ASIGNACION',
            prioridad = 1,
            notas_adicionales = ?
        WHERE id = ?
    ''', (notas_actuales + nueva_nota, turno_id))
    
    # Registrar en historial
    registrar_historial(turno_id, 'PACIENTE_AFILIADO', 'Afiliación completada - Esperando doctor')
    
    # Asignar a lista de espera de doctor automáticamente
    resultado = asignar_a_lista_espera_doctor(conn, turno_id)
    
    respuesta = {
        'success': True,
        'message': 'Paciente afiliado exitosamente',
        'estado': 'ESPERANDO_ASIGNACION',
        'prioridad': 1
    }
    
    if resultado.get('asignado'):
        respuesta['asignado_lista_espera'] = True
        respuesta['doctor_asignado'] = resultado.get('doctor_nombre')
        respuesta['message'] = f'Paciente afiliado y asignado al Dr. {resultado.get("doctor_nombre")}'
    
    return jsonify(respuesta)

@app.route('/api/trabajo-social/estadisticas')
@with_db_connection
def estadisticas_afiliaciones(conn):
    """Estadísticas simples de afiliaciones"""
    
    hoy = datetime.now().strftime('%Y-%m-%d')
    
    # Pacientes pendientes de afiliación
    pendientes = conn.execute('''
        SELECT COUNT(*) as count
        FROM turnos 
        WHERE estacion_actual = 2
          AND estado = 'PENDIENTE'
          AND tipo = 'SIN_CITA'
          AND DATE(timestamp_creacion) = ?
    ''', (hoy,)).fetchone()['count']
    
    # Pacientes afiliados hoy
    afiliados_hoy = conn.execute('''
        SELECT COUNT(*) as count
        FROM historial_turnos 
        WHERE DATE(timestamp) = ?
          AND accion = 'PACIENTE_AFILIADO'
    ''', (hoy,)).fetchone()['count']
    
    return jsonify({
        'success': True,
        'pendientes': pendientes,
        'afiliados_hoy': afiliados_hoy,
        'fecha': hoy
    })

# ========== FUNCIONES ADMINISTRATIVAS ==========

@app.route('/api/doctores/forzar-ausentes', methods=['POST'])
@with_db_connection
def forzar_doctores_ausentes(conn):
    try:
        # Se actualizan todos los doctores a estado ausente
        conn.execute('UPDATE doctores SET activo = 0, estado_detallado = "AUSENTE"')
        
        # Se cuenta cuantos doctores se actualizaron
        count = conn.execute('SELECT changes()').fetchone()[0]
        
        return jsonify({'success': True, 'message': f'Se actualizaron {count} doctores a estado AUSENTE'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/turnos/<int:turno_id>/recibir-retorno', methods=['POST'])
@with_db_connection
def recibir_retorno(conn, turno_id):
    try:
        # Se actualiza el turno de retorno a estado "en atencion"
        conn.execute('''
            UPDATE turnos 
            SET estado = "EN_ATENCION"
            WHERE id = ?
        ''', (turno_id,))
        
        # Se registra en el historial
        registrar_historial(turno_id, 'RETORNO_RECIBIDO', 'Paciente de vuelta en consulta')
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== INICIALIZACION DE LA APLICACION ==========

if __name__ == '__main__':
    # Se importa e inicializa la base de datos
    from database import init_db
    init_db()
    
    # Se inicia el servidor Flask
    print("Iniciando servidor Flask...")
    print("Sistema de Turnos Oftalmológico")
    print("Servidor corriendo en: http://127.0.0.1:5000")
    print("Rutas disponibles:")
    print("   - / (Recepción)")
    print("   - /doctor-login (Login doctores)")
    print("   - /doctor-dashboard (Dashboard doctores)")
    print("   - /toma-calculos-dashboard (Dashboard toma de cálculos)")
    print("   - /trabajo-social-dashboard (Dashboard trabajo social)")
    
    app.run(debug=True, host='127.0.0.1', port=5000)