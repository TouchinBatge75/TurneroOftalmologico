# database.py
import sqlite3
from datetime import datetime

def get_db_connection():
    conn = sqlite3.connect('turnos.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    
    try:
        # Tabla de doctores
        conn.execute('''
            CREATE TABLE IF NOT EXISTS doctores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                especialidad TEXT,
                activo BOOLEAN DEFAULT 0,
                disponible BOOLEAN DEFAULT 1,
                estado_detallado TEXT DEFAULT 'AUSENTE'
            )
        ''')
        print("✅ Tabla 'doctores' creada")

        # Tabla de Consultorios
        conn.execute('''
            CREATE TABLE IF NOT EXISTS consultorios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero TEXT NOT NULL UNIQUE,
                ocupado BOOLEAN DEFAULT 0,
                doctor_actual INTEGER,
                timestamp_ocupado DATETIME,
                FOREIGN KEY (doctor_actual) REFERENCES doctores (id)
            )
        ''')
        print("✅ Tabla 'consultorios' creada")

        # Tabla de estaciones
        conn.execute('''
            CREATE TABLE IF NOT EXISTS estaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                descripcion TEXT
            )
        ''')
        print("✅ Tabla 'estaciones' creada")
        
        # Tabla de turnos (versión básica primero)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS turnos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero TEXT NOT NULL,
                paciente_nombre TEXT NOT NULL,
                paciente_edad INTEGER,
                tipo TEXT DEFAULT 'CITA',
                estado TEXT DEFAULT 'PENDIENTE',
                estacion_actual INTEGER,
                estacion_siguiente INTEGER,
                doctor_asignado INTEGER,
                prioridad INTEGER DEFAULT 1,
                timestamp_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                timestamp_atencion DATETIME,
                timestamp_cancelado DATETIME,
                razon_cancelacion TEXT,
                tiempo_total INTEGER,
                FOREIGN KEY (estacion_actual) REFERENCES estaciones (id),
                FOREIGN KEY (estacion_siguiente) REFERENCES estaciones (id),
                FOREIGN KEY (doctor_asignado) REFERENCES doctores (id)
            )
        ''')
        print("✅ Tabla 'turnos' creada")
        
        # AGREGAR CAMPOS NUEVOS SI NO EXISTEN
        try:
            conn.execute('ALTER TABLE turnos ADD COLUMN notas_adicionales TEXT DEFAULT ""')
            print("✅ Campo 'notas_adicionales' agregado")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("ℹ️ Campo 'notas_adicionales' ya existe")
            else:
                raise e
                
        try:
            conn.execute('ALTER TABLE turnos ADD COLUMN historial_notas TEXT DEFAULT "[]"')
            print("✅ Campo 'historial_notas' agregado")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("ℹ️ Campo 'historial_notas' ya existe")
            else:
                raise e
        
        # Tabla de historial para estadísticas
        conn.execute('''
            CREATE TABLE IF NOT EXISTS historial_turnos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turno_id INTEGER NOT NULL,
                accion TEXT NOT NULL,
                detalles TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                usuario TEXT DEFAULT 'sistema',
                FOREIGN KEY (turno_id) REFERENCES turnos (id)
            )
        ''')
        print("✅ Tabla 'historial_turnos' creada")

        # Tabla de mediciones
        conn.execute('''
            CREATE TABLE IF NOT EXISTS mediciones_calculos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turno_id INTEGER NOT NULL,
                agudeza_visual_od TEXT,
                agudeza_visual_oi TEXT,
                presion_intraocular_od TEXT,
                presion_intraocular_oi TEXT,
                queratometria_od TEXT,
                queratometria_oi TEXT,
                refraccion_od TEXT,
                refraccion_oi TEXT,
                observaciones TEXT,
                atendido_por TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (turno_id) REFERENCES turnos (id)
            )
        ''')
        print("✅ Tabla 'mediciones_calculos' creada")
        
        # Insertar estaciones básicas
        estaciones = [
            ('Recepción', 'Punto de entrada y salida del paciente'),
            ('Trabajo Social', 'Atención social para pacientes sin cita, asi como para agendar operaciones'),
            ('Toma de Calculos Correspondientes', 'Medición de agudeza visual, Presion Intraocular, Queratometria, Tonometria, Calculo de LIO, Refraccion'),
            ('Consulta Médica', 'Consulta con el medico asignado'),
            ('Farmacia', 'Entrega de medicamentos'),
            ('Asesoria Visual', 'Orientación sobre lentes'),
            ('Estudios Especiales', 'Exámenes especializados'),
            ('Salida', 'Final del proceso')
        ]

        consultorios = [
            ('Consultorio 1',),
            ('Consultorio 2',),
            ('Consultorio 3',), 
            ('Consultorio 4',),
            ('Consultorio 5',)
        ]
        
        conn.executemany(
            'INSERT OR IGNORE INTO estaciones (nombre, descripcion) VALUES (?, ?)',
            estaciones
        )
        print("✅ 8 estaciones insertadas")

        conn.executemany(
            'INSERT OR IGNORE INTO consultorios (numero) VALUES (?)',
            consultorios
        )
        print("✅ 5 consultorios insertados")
        
        # NO insertar doctores - la tabla estará vacía
        print("ℹ️  Tabla de doctores creada vacía - agrega doctores desde la interfaz")
        
        conn.commit()
        print("✅ Todos los cambios guardados en la base de datos")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
    finally:
        conn.close()
        print("✅ Conexión cerrada correctamente")

if __name__ == '__main__':
    init_db()
    print("🎉 Base de datos inicializada correctamente!")