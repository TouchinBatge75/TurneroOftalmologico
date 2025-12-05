# db_utils.py
import sqlite3
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

@contextmanager
def get_db_connection():
    """
    Se encarga de manejar las conexiones a la base de datos de forma segura
    Abre la conexion, ejecuta el codigo, y cierra la conexion siempre
    """
    conn = None
    try:
        # Se abre la conexion a la base de datos
        conn = sqlite3.connect('turnos.db', timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        logger.info("Conexion a BD establecida")
        
        # Se pasa la conexion al codigo que la necesita
        yield conn
        
        # Se confirman los cambios
        conn.commit()
        logger.info("Transaccion confirmada")
        
    except sqlite3.Error as e:
        # Si hay error, se revierte
        if conn:
            conn.rollback()
            logger.error(f"Error en BD - Rollback: {e}")
        raise e
        
    except Exception as e:
        # Si hay cualquier otro error, tambien se revierten los cambios
        if conn:
            conn.rollback()
            logger.error(f"Error general - Rollback: {e}")
        raise e
        
    finally:
        # Esto se ejecuta 
        if conn:
            conn.close()
            logger.info("Conexion a BD cerrada")