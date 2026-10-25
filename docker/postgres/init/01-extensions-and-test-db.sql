-- Se ejecuta una sola vez, cuando el volumen de datos está vacío.

-- Extensión de vectores en la base principal.
CREATE EXTENSION IF NOT EXISTS vector;

-- Base aparte para las pruebas automáticas: así nunca tocan tus datos reales.
CREATE DATABASE jarvis_test;
\connect jarvis_test
CREATE EXTENSION IF NOT EXISTS vector;
