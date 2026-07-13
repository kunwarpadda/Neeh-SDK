#ifndef NEEH_C_API_H
#define NEEH_C_API_H

#include <neeh/export.h>

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NEEH_ABI_VERSION 1u

typedef enum neeh_status {
    NEEH_STATUS_OK = 0,
    NEEH_STATUS_INVALID_ARGUMENT = 1,
    NEEH_STATUS_OUT_OF_RANGE = 2,
    NEEH_STATUS_NOT_FOUND = 3,
    NEEH_STATUS_LOCKED = 4,
    NEEH_STATUS_CONFLICT = 5,
    NEEH_STATUS_BUFFER_TOO_SMALL = 6,
    NEEH_STATUS_OUT_OF_MEMORY = 7,
    NEEH_STATUS_INTERNAL = 8
} neeh_status_t;

typedef enum neeh_author {
    NEEH_AUTHOR_USER = 0,
    NEEH_AUTHOR_AGENT = 1
} neeh_author_t;

typedef enum neeh_brush {
    NEEH_BRUSH_PEN = 0,
    NEEH_BRUSH_MARKER = 1,
    NEEH_BRUSH_HIGHLIGHTER = 2
} neeh_brush_t;

typedef struct neeh_document neeh_document_t;
typedef struct neeh_stroke neeh_stroke_t;
typedef struct neeh_stroke_list neeh_stroke_list_t;
typedef struct neeh_string neeh_string_t;
typedef struct neeh_image neeh_image_t;

typedef struct neeh_point {
    double x;
    double y;
    int64_t t_ms;
    float pressure;
    float tilt_x;
    float tilt_y;
} neeh_point_t;

typedef struct neeh_bbox {
    double min_x;
    double min_y;
    double max_x;
    double max_y;
} neeh_bbox_t;

/* Descriptor strings are borrowed through the consuming call; the core copies them. */
typedef struct neeh_stroke_style {
    const char* color;
    double width;
    neeh_brush_t brush;
    double opacity;
} neeh_stroke_style_t;

typedef struct neeh_stroke_desc {
    const neeh_point_t* points;
    size_t point_count;
    neeh_stroke_style_t style;
    const char* id; /* NULL generates st_...; an explicit empty/blank id is invalid. */
    neeh_author_t author;
    int64_t created_at_ms; /* INT64_MIN asks the core to use wall-clock time. */
} neeh_stroke_desc_t;

typedef struct neeh_document_desc {
    const char* title;
    const char* id; /* NULL generates doc_...; an explicit empty/blank id is invalid. */
    int64_t created_at_ms; /* INT64_MIN asks the core to use wall-clock time. */
    uint8_t create_default_page;
} neeh_document_desc_t;

typedef struct neeh_page_desc {
    double width;
    double height;
    const char* background;
    const char* id; /* NULL generates pg_...; an explicit empty/blank id is invalid. */
    uint8_t create_default_layer;
} neeh_page_desc_t;

typedef struct neeh_layer_desc {
    const char* name;
    neeh_author_t author;
    const char* id; /* NULL generates ly_...; an explicit empty/blank id is invalid. */
    uint8_t visible;
    uint8_t locked;
} neeh_layer_desc_t;

typedef struct neeh_page_info {
    double width;
    double height;
    size_t layer_count;
} neeh_page_info_t;

typedef struct neeh_layer_info {
    neeh_author_t author;
    uint8_t visible;
    uint8_t locked;
    size_t stroke_count;
} neeh_layer_info_t;

typedef struct neeh_stroke_info {
    neeh_author_t author;
    int64_t created_at_ms;
    size_t point_count;
    double width;
    neeh_brush_t brush;
    double opacity;
} neeh_stroke_info_t;

typedef enum neeh_direction {
    NEEH_DIRECTION_RIGHT = 0,
    NEEH_DIRECTION_DOWN_RIGHT = 1,
    NEEH_DIRECTION_DOWN = 2,
    NEEH_DIRECTION_DOWN_LEFT = 3,
    NEEH_DIRECTION_LEFT = 4,
    NEEH_DIRECTION_UP_LEFT = 5,
    NEEH_DIRECTION_UP = 6,
    NEEH_DIRECTION_UP_RIGHT = 7,
    NEEH_DIRECTION_CLOSED_OR_STATIONARY = 8
} neeh_direction_t;

/* Deterministic per-stroke measurement record (ink-analysis/v1 parity).
 * Halves are relative to the page frame passed to (or implied by) the call. */
typedef struct neeh_mark_analysis {
    neeh_bbox_t bbox;
    double center_x;
    double center_y;
    int64_t start_ms;
    int64_t end_ms;
    int64_t duration_ms;
    uint8_t upper_half;
    uint8_t left_half;
    neeh_direction_t direction;
    double path_length;
    double pressure_mean;
    double pressure_min;
    double pressure_max;
} neeh_mark_analysis_t;

/* Error text is thread-local and valid until the next status-returning call on that thread. */
NEEH_API uint32_t neeh_abi_version(void);
NEEH_API const char* neeh_status_name(neeh_status_t status);
NEEH_API const char* neeh_last_error_message(void);

NEEH_API neeh_stroke_style_t neeh_stroke_style_default(void);
NEEH_API neeh_stroke_style_t neeh_stroke_style_highlighter(const char* color, double width);
NEEH_API neeh_document_desc_t neeh_document_desc_default(void);
NEEH_API neeh_page_desc_t neeh_page_desc_default(void);
NEEH_API neeh_layer_desc_t neeh_layer_desc_default(void);

/*
 * Every handle returned through **out is owned by the caller. Destroy is NULL-safe.
 * Mutable handles require external synchronization when shared across threads.
 * For copy_* calls, out_required_size includes the trailing NUL. Passing buffer=NULL
 * queries that size; a short non-NULL buffer returns NEEH_STATUS_BUFFER_TOO_SMALL.
 */
NEEH_API neeh_status_t neeh_stroke_create(
    const neeh_stroke_desc_t* desc,
    neeh_stroke_t** out_stroke);
NEEH_API void neeh_stroke_destroy(neeh_stroke_t* stroke);
NEEH_API neeh_status_t neeh_stroke_clone(
    const neeh_stroke_t* stroke,
    neeh_stroke_t** out_stroke);
NEEH_API neeh_status_t neeh_stroke_translate(
    const neeh_stroke_t* stroke,
    double dx,
    double dy,
    neeh_stroke_t** out_stroke);
NEEH_API neeh_status_t neeh_stroke_get_info(
    const neeh_stroke_t* stroke,
    neeh_stroke_info_t* out_info);
NEEH_API neeh_status_t neeh_stroke_get_bbox(
    const neeh_stroke_t* stroke,
    neeh_bbox_t* out_bbox);
NEEH_API neeh_status_t neeh_stroke_get_duration_ms(
    const neeh_stroke_t* stroke,
    int64_t* out_duration_ms);
NEEH_API neeh_status_t neeh_stroke_get_point(
    const neeh_stroke_t* stroke,
    size_t index,
    neeh_point_t* out_point);
NEEH_API neeh_status_t neeh_stroke_copy_id(
    const neeh_stroke_t* stroke,
    char* buffer,
    size_t capacity,
    size_t* out_required_size);
NEEH_API neeh_status_t neeh_stroke_copy_color(
    const neeh_stroke_t* stroke,
    char* buffer,
    size_t capacity,
    size_t* out_required_size);

NEEH_API neeh_status_t neeh_document_create(
    const neeh_document_desc_t* desc,
    neeh_document_t** out_document);
NEEH_API void neeh_document_destroy(neeh_document_t* document);
NEEH_API neeh_status_t neeh_document_copy_id(
    const neeh_document_t* document,
    char* buffer,
    size_t capacity,
    size_t* out_required_size);
NEEH_API neeh_status_t neeh_document_copy_title(
    const neeh_document_t* document,
    char* buffer,
    size_t capacity,
    size_t* out_required_size);
NEEH_API neeh_status_t neeh_document_set_title(
    neeh_document_t* document,
    const char* title);
NEEH_API neeh_status_t neeh_document_get_created_at_ms(
    const neeh_document_t* document,
    int64_t* out_created_at_ms);
NEEH_API neeh_status_t neeh_document_get_page_count(
    const neeh_document_t* document,
    size_t* out_count);
NEEH_API neeh_status_t neeh_document_add_page(
    neeh_document_t* document,
    const neeh_page_desc_t* desc,
    size_t* out_page_index);
NEEH_API neeh_status_t neeh_document_remove_page(
    neeh_document_t* document,
    size_t page_index);
NEEH_API neeh_status_t neeh_document_get_page_info(
    const neeh_document_t* document,
    size_t page_index,
    neeh_page_info_t* out_info);
NEEH_API neeh_status_t neeh_document_copy_page_id(
    const neeh_document_t* document,
    size_t page_index,
    char* buffer,
    size_t capacity,
    size_t* out_required_size);
NEEH_API neeh_status_t neeh_document_copy_page_background(
    const neeh_document_t* document,
    size_t page_index,
    char* buffer,
    size_t capacity,
    size_t* out_required_size);

NEEH_API neeh_status_t neeh_page_add_layer(
    neeh_document_t* document,
    size_t page_index,
    const neeh_layer_desc_t* desc,
    size_t* out_layer_index);
NEEH_API neeh_status_t neeh_page_remove_layer(
    neeh_document_t* document,
    size_t page_index,
    size_t layer_index);
NEEH_API neeh_status_t neeh_page_get_layer_info(
    const neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    neeh_layer_info_t* out_info);
NEEH_API neeh_status_t neeh_page_copy_layer_id(
    const neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    char* buffer,
    size_t capacity,
    size_t* out_required_size);
NEEH_API neeh_status_t neeh_page_copy_layer_name(
    const neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    char* buffer,
    size_t capacity,
    size_t* out_required_size);
NEEH_API neeh_status_t neeh_layer_set_visible(
    neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    uint8_t visible);
NEEH_API neeh_status_t neeh_layer_set_locked(
    neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    uint8_t locked);

/* Adds a copy; the caller retains ownership of stroke. */
NEEH_API neeh_status_t neeh_layer_add_stroke(
    neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    const neeh_stroke_t* stroke);
/* NULL/empty layer_key routes agent ink to an agent layer and user ink to ink. */
NEEH_API neeh_status_t neeh_page_add_stroke(
    neeh_document_t* document,
    size_t page_index,
    const neeh_stroke_t* stroke,
    const char* layer_key,
    size_t* out_layer_index);
/* out_removed may be NULL; otherwise it receives an independently owned handle. */
NEEH_API neeh_status_t neeh_page_remove_stroke(
    neeh_document_t* document,
    size_t page_index,
    const char* stroke_id,
    neeh_stroke_t** out_removed);
NEEH_API neeh_status_t neeh_page_translate_stroke(
    neeh_document_t* document,
    size_t page_index,
    const char* stroke_id,
    double dx,
    double dy);
NEEH_API neeh_status_t neeh_page_restyle_stroke(
    neeh_document_t* document,
    size_t page_index,
    const char* stroke_id,
    const neeh_stroke_style_t* style);
NEEH_API neeh_status_t neeh_page_find_stroke(
    const neeh_document_t* document,
    size_t page_index,
    const char* stroke_id,
    size_t* out_layer_index,
    size_t* out_stroke_index);

/* Query results are immutable snapshots; they remain valid after document mutation. */
NEEH_API neeh_status_t neeh_page_list_strokes(
    const neeh_document_t* document,
    size_t page_index,
    uint8_t visible_only,
    neeh_stroke_list_t** out_list);
NEEH_API neeh_status_t neeh_page_query_region(
    const neeh_document_t* document,
    size_t page_index,
    const neeh_bbox_t* region,
    uint8_t visible_only,
    neeh_stroke_list_t** out_list);
NEEH_API neeh_status_t neeh_page_query_since(
    const neeh_document_t* document,
    size_t page_index,
    int64_t epoch_ms,
    neeh_stroke_list_t** out_list);
NEEH_API void neeh_stroke_list_destroy(neeh_stroke_list_t* list);
NEEH_API neeh_status_t neeh_stroke_list_get_count(
    const neeh_stroke_list_t* list,
    size_t* out_count);
NEEH_API neeh_status_t neeh_stroke_list_get(
    const neeh_stroke_list_t* list,
    size_t index,
    neeh_stroke_t** out_stroke);

NEEH_API const char* neeh_direction_name(neeh_direction_t direction);

/* Analyze one stroke against a page frame (page width/height decide halves). */
NEEH_API neeh_status_t neeh_stroke_analyze(
    const neeh_stroke_t* stroke,
    double page_width,
    double page_height,
    neeh_mark_analysis_t* out_analysis);

/* The most recently finished visible stroke on the page, by (end time, start
 * time, page order). Empty page returns NEEH_STATUS_NOT_FOUND. Either output
 * may be NULL (but not both); out_stroke follows handle ownership rules. */
NEEH_API neeh_status_t neeh_page_latest_mark(
    const neeh_document_t* document,
    size_t page_index,
    neeh_mark_analysis_t* out_analysis,
    neeh_stroke_t** out_stroke);

/* All visible strokes in chronological order (start time, end time, page
 * order) as an immutable snapshot list. */
NEEH_API neeh_status_t neeh_page_creation_order(
    const neeh_document_t* document,
    size_t page_index,
    neeh_stroke_list_t** out_list);

NEEH_API neeh_status_t neeh_document_render_page_svg(
    const neeh_document_t* document,
    size_t page_index,
    const neeh_bbox_t* region,
    double scale,
    neeh_string_t** out_svg);
NEEH_API void neeh_string_destroy(neeh_string_t* string_value);
/* Borrowed view valid until neeh_string_destroy. SVG data is not NUL-dependent. */
NEEH_API const char* neeh_string_data(const neeh_string_t* string_value);
NEEH_API size_t neeh_string_size(const neeh_string_t* string_value);

NEEH_API neeh_status_t neeh_document_render_page_rgba(
    const neeh_document_t* document,
    size_t page_index,
    const neeh_bbox_t* region,
    uint32_t width,
    uint32_t height,
    neeh_image_t** out_image);
NEEH_API void neeh_image_destroy(neeh_image_t* image);
/* Borrowed RGBA8 view valid until neeh_image_destroy. */
NEEH_API const uint8_t* neeh_image_data(const neeh_image_t* image);
NEEH_API size_t neeh_image_size(const neeh_image_t* image);
NEEH_API uint32_t neeh_image_width(const neeh_image_t* image);
NEEH_API uint32_t neeh_image_height(const neeh_image_t* image);
NEEH_API size_t neeh_image_stride(const neeh_image_t* image);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif
