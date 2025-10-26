"""
Sistema de caché simple para mejorar rendimiento
"""
from datetime import datetime, timedelta


class SimpleCache:
    """Caché en memoria para datos frecuentes"""

    def __init__(self):
        self._cache = {}
        self._cache_duration = timedelta(minutes=5)

    def get(self, key):
        """Obtiene un valor del caché si es válido"""
        if key in self._cache:
            data, timestamp = self._cache[key]
            if datetime.now() - timestamp < self._cache_duration:
                return data
            else:
                del self._cache[key]
        return None

    def set(self, key, value):
        """Almacena un valor en el caché"""
        self._cache[key] = (value, datetime.now())

    def clear(self, key=None):
        """Limpia el caché"""
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()


# Instancia global del caché
cache = SimpleCache()
