# estadisticas.py
import sqlite3
from datetime import datetime

from db_utils import get_db_connection
from datetime import datetime

def registrar_historial(turno_id, accion, detalles="", usuario="sistema"):
    """Registra una acción en el historial para estadísticas"""
    try:
        with get_db_connection() as conn:
            conn.execute('''
                INSERT INTO historial_turnos (turno_id, accion, detalles, usuario)
                VALUES (?, ?, ?, ?)
            ''', (turno_id, accion, detalles, usuario))
        return True
    except Exception as e:
        print(f"Error en registrar_historial: {e}")
        return False

def verificar_columna_existe(tabla, columna):
    """Verifica si una columna existe en una tabla"""
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(f"PRAGMA table_info({tabla})")
            columnas = [col[1] for col in cursor.fetchall()]
            return columna in columnas
    except:
        return False


def registrar_historial(turno_id, accion, detalles="", usuario="sistema"):
    """Registra una acción en el historial para estadísticas"""
    try:
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO historial_turnos (turno_id, accion, detalles, usuario)
            VALUES (?, ?, ?, ?)
        ''', (turno_id, accion, detalles, usuario))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error en registrar_historial: {e}")
        return False

def verificar_columna_existe(tabla, columna):
    """Verificacion de si una columna existe en una tabla"""
    try:
        conn = get_db_connection()
        cursor = conn.execute(f"PRAGMA table_info({tabla})")
        columnas = [col[1] for col in cursor.fetchall()]
        conn.close()
        return columna in columnas
    except:
        return False

def obtener_estadisticas_dia(fecha=None):
    """Se obtienen estadísticas del día especificado (u hoy)"""
    try:
        if fecha is None:
            fecha = datetime.now().strftime('%Y-%m-%d')
        
        conn = get_db_connection()
        
        # Consulta básica que siempre funciona
        stats = conn.execute('''
            SELECT 
                COUNT(*) as total_turnos,
                SUM(CASE WHEN estado = 'CANCELADO' THEN 1 ELSE 0 END) as cancelados,
                SUM(CASE WHEN estado = 'FINALIZADO' THEN 1 ELSE 0 END) as finalizados,
                SUM(CASE WHEN estado NOT IN ('CANCELADO', 'FINALIZADO') THEN 1 ELSE 0 END) as activos
            FROM turnos 
            WHERE DATE(timestamp_creacion) = ?
        ''', (fecha,)).fetchone()
        
        # Solo se obtienen razones si la columna existe
        cancelaciones_por_razon = []
        if verificar_columna_existe('turnos', 'razon_cancelacion'):
            cancelaciones = conn.execute('''
                SELECT razon_cancelacion, COUNT(*) as cantidad
                FROM turnos 
                WHERE DATE(timestamp_creacion) = ? AND estado = 'CANCELADO'
                GROUP BY razon_cancelacion
            ''', (fecha,)).fetchall()
            cancelaciones_por_razon = [dict(c) for c in cancelaciones]
        
        conn.close()
        
        total = stats['total_turnos'] or 0
        cancelados = stats['cancelados'] or 0
        
        return {
            'fecha': fecha,
            'total_turnos': total,
            'cancelados': cancelados,
            'finalizados': stats['finalizados'] or 0,
            'activos': stats['activos'] or 0,
            'tasa_cancelacion': (cancelados / total * 100) if total > 0 else 0,
            'cancelaciones_por_razon': cancelaciones_por_razon
        }
    except Exception as e:
        print(f"Error en obtener_estadisticas_dia: {e}")
        return {
            'fecha': fecha,
            'total_turnos': 0,
            'cancelados': 0,
            'finalizados': 0,
            'activos': 0,
            'tasa_cancelacion': 0,
            'cancelaciones_por_razon': []
        }

def obtener_estadisticas_mensual(mes=None, año=None):
    """Se obtienen estadísticas del mes especificado"""
    try:
        if mes is None:
            mes = datetime.now().month
        if año is None:
            año = datetime.now().year
        
        conn = get_db_connection()
        
        stats = conn.execute('''
            SELECT 
                COUNT(*) as total_turnos,
                SUM(CASE WHEN estado = 'CANCELADO' THEN 1 ELSE 0 END) as cancelados,
                SUM(CASE WHEN estado = 'FINALIZADO' THEN 1 ELSE 0 END) as finalizados
            FROM turnos 
            WHERE strftime('%Y-%m', timestamp_creacion) = ?
        ''', (f'{año}-{mes:02d}',)).fetchone()
        
        # Tendencia diaria del mes
        tendencia = conn.execute('''
            SELECT 
                DATE(timestamp_creacion) as fecha,
                COUNT(*) as turnos,
                SUM(CASE WHEN estado = 'CANCELADO' THEN 1 ELSE 0 END) as cancelados
            FROM turnos 
            WHERE strftime('%Y-%m', timestamp_creacion) = ?
            GROUP BY DATE(timestamp_creacion)
            ORDER BY fecha
        ''', (f'{año}-{mes:02d}',)).fetchall()
        
        conn.close()
        
        total = stats['total_turnos'] or 0
        cancelados = stats['cancelados'] or 0
        
        return {
            'mes': f'{año}-{mes:02d}',
            'total_turnos': total,
            'cancelados': cancelados,
            'finalizados': stats['finalizados'] or 0,
            'tasa_cancelacion': (cancelados / total * 100) if total > 0 else 0,
            'tendencia_diaria': [dict(t) for t in tendencia]
        }
    except Exception as e:
        print(f"Error en obtener_estadisticas_mensual: {e}")
        return {
            'mes': f'{año}-{mes:02d}',
            'total_turnos': 0,
            'cancelados': 0,
            'finalizados': 0,
            'tasa_cancelacion': 0,
            'tendencia_diaria': []
        }

if __name__ == '__main__':
    print("Probando estadísticas...")
    print("¿Columna razon_cancelacion existe?", verificar_columna_existe('turnos', 'razon_cancelacion'))
    print("Día:", obtener_estadisticas_dia())
    print("Mes:", obtener_estadisticas_mensual())