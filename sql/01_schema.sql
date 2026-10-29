-- Olist 原始层（SQLite）——由 olist-biz-analytics 的 MySQL DDL（sql/01_schema.sql）移植。
-- 对账项目的结构冻结基线（P0）。列名与 Kaggle CSV 表头一一对应。
--
-- 设计规则（与旧 MySQL 版不同，有意为之）：
--   原始层不设 PRIMARY KEY / UNIQUE / NOT NULL 约束，加载永不丢行；
--   重复键（如重复 order_id、重复 review_id）是对账要*测量*的异常，不是加载时静默丢弃的对象。
--   唯一性/一致性校验属于对账引擎（src/matcher）与盘点脚本（scripts/）。
-- 日期字段一律 TEXT（ISO "YYYY-MM-DD HH:MM:SS"），金额 REAL，计数 INTEGER。

CREATE TABLE orders (
  order_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  order_status TEXT NOT NULL,
  order_purchase_timestamp TEXT,
  order_approved_at TEXT,
  order_delivered_carrier_date TEXT,
  order_delivered_customer_date TEXT,
  order_estimated_delivery_date TEXT
);
CREATE INDEX idx_orders_order_id ON orders(order_id);
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(order_status);
CREATE INDEX idx_orders_purchase_ts ON orders(order_purchase_timestamp);

CREATE TABLE order_items (
  order_id TEXT NOT NULL,
  order_item_id INTEGER NOT NULL,
  product_id TEXT NOT NULL,
  seller_id TEXT NOT NULL,
  shipping_limit_date TEXT,
  price REAL,
  freight_value REAL
);
CREATE INDEX idx_items_order_id ON order_items(order_id);
CREATE INDEX idx_items_product_id ON order_items(product_id);
CREATE INDEX idx_items_seller_id ON order_items(seller_id);

CREATE TABLE order_payments (
  order_id TEXT NOT NULL,
  payment_sequential INTEGER NOT NULL,
  payment_type TEXT,
  payment_installments INTEGER,
  payment_value REAL
);
CREATE INDEX idx_payments_order_id ON order_payments(order_id);
CREATE INDEX idx_payments_type ON order_payments(payment_type);

CREATE TABLE order_reviews (
  review_id TEXT NOT NULL,
  order_id TEXT NOT NULL,
  review_score INTEGER,
  review_comment_title TEXT,
  review_comment_message TEXT,
  review_creation_date TEXT,
  review_answer_timestamp TEXT
);
CREATE INDEX idx_reviews_order_id ON order_reviews(order_id);

CREATE TABLE customers (
  customer_id TEXT NOT NULL,
  customer_unique_id TEXT NOT NULL,
  customer_zip_code_prefix INTEGER,
  customer_city TEXT,
  customer_state TEXT
);
CREATE INDEX idx_customers_customer_id ON customers(customer_id);
CREATE INDEX idx_customers_unique ON customers(customer_unique_id);

CREATE TABLE sellers (
  seller_id TEXT NOT NULL,
  seller_zip_code_prefix INTEGER,
  seller_city TEXT,
  seller_state TEXT
);
CREATE INDEX idx_sellers_seller_id ON sellers(seller_id);

CREATE TABLE products (
  product_id TEXT NOT NULL,
  product_category_name TEXT,
  product_name_lenght INTEGER,
  product_description_lenght INTEGER,
  product_photos_qty INTEGER,
  product_weight_g INTEGER,
  product_length_cm INTEGER,
  product_height_cm INTEGER,
  product_width_cm INTEGER
);
CREATE INDEX idx_products_product_id ON products(product_id);
CREATE INDEX idx_products_category ON products(product_category_name);

-- 原始 geolocation：zip 前缀不唯一（同一前缀多坐标），保留原始行
CREATE TABLE geolocation (
  geolocation_zip_code_prefix INTEGER,
  geolocation_lat REAL,
  geolocation_lng REAL,
  geolocation_city TEXT,
  geolocation_state TEXT
);
CREATE INDEX idx_geo_zip ON geolocation(geolocation_zip_code_prefix);

CREATE TABLE product_category_translation (
  product_category_name TEXT NOT NULL,
  product_category_name_english TEXT
);
CREATE INDEX idx_cat_name ON product_category_translation(product_category_name);
