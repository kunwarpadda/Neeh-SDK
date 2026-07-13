#include <neeh/c_api.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;

#define CHECK(condition)                                                                    \
    do {                                                                                    \
        if (!(condition)) {                                                                 \
            fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #condition); \
            ++failures;                                                                     \
        }                                                                                   \
    } while (0)

#define CHECK_STATUS(expression, expected)                                                     \
    do {                                                                                        \
        neeh_status_t actual_status = (expression);                                              \
        if (actual_status != (expected)) {                                                       \
            fprintf(                                                                            \
                stderr,                                                                         \
                "%s:%d: status %s, expected %s: %s\n",                                        \
                __FILE__,                                                                       \
                __LINE__,                                                                       \
                neeh_status_name(actual_status),                                                 \
                neeh_status_name((expected)),                                                    \
                neeh_last_error_message());                                                      \
            ++failures;                                                                         \
        }                                                                                       \
    } while (0)

static void copy_stroke_id(const neeh_stroke_t* stroke, char* buffer, size_t capacity) {
    size_t required = 0;
    CHECK_STATUS(neeh_stroke_copy_id(stroke, NULL, 0, &required), NEEH_STATUS_OK);
    CHECK(required <= capacity);
    if (required <= capacity) {
        CHECK_STATUS(neeh_stroke_copy_id(stroke, buffer, capacity, &required), NEEH_STATUS_OK);
    }
}

int main(void) {
    neeh_document_t* document = NULL;
    neeh_stroke_t* stroke = NULL;
    neeh_stroke_t* translated = NULL;
    neeh_stroke_t* cloned = NULL;
    neeh_stroke_t* snapshot_stroke = NULL;
    neeh_stroke_t* removed = NULL;
    neeh_stroke_list_t* list = NULL;
    neeh_string_t* svg = NULL;
    neeh_image_t* image = NULL;

    CHECK(neeh_abi_version() == NEEH_ABI_VERSION);
    CHECK(strcmp(neeh_status_name(NEEH_STATUS_LOCKED), "locked") == 0);

    neeh_point_t points[3] = {
        {2.0, 3.0, 10, 0.25F, 5.0F, -5.0F},
        {8.0, 9.0, 20, 0.75F, 6.0F, -6.0F},
        {14.0, 15.0, 40, 1.0F, 7.0F, -7.0F},
    };
    neeh_stroke_desc_t stroke_desc;
    stroke_desc.points = points;
    stroke_desc.point_count = 3;
    stroke_desc.style = neeh_stroke_style_default();
    stroke_desc.style.color = "#336699";
    stroke_desc.style.width = 3.0;
    stroke_desc.id = "st_c_abi";
    stroke_desc.author = NEEH_AUTHOR_AGENT;
    stroke_desc.created_at_ms = 123456;

    CHECK_STATUS(neeh_stroke_create(&stroke_desc, &stroke), NEEH_STATUS_OK);
    CHECK(stroke != NULL);

    neeh_stroke_desc_t blank_id_desc = stroke_desc;
    blank_id_desc.id = " \t";
    neeh_stroke_t* blank_id_stroke = NULL;
    CHECK_STATUS(
        neeh_stroke_create(&blank_id_desc, &blank_id_stroke),
        NEEH_STATUS_INVALID_ARGUMENT);
    CHECK(blank_id_stroke == NULL);

    neeh_stroke_desc_t invalid_stroke_desc = stroke_desc;
    invalid_stroke_desc.id = "st_invalid_pressure";
    neeh_point_t invalid_point = {0.0, 0.0, 0, 1.1F, 0.0F, 0.0F};
    invalid_stroke_desc.points = &invalid_point;
    invalid_stroke_desc.point_count = 1;
    neeh_stroke_t* invalid_stroke = NULL;
    CHECK_STATUS(
        neeh_stroke_create(&invalid_stroke_desc, &invalid_stroke),
        NEEH_STATUS_INVALID_ARGUMENT);
    CHECK(invalid_stroke == NULL);
    invalid_stroke_desc = stroke_desc;
    invalid_stroke_desc.id = "st_invalid_color";
    invalid_stroke_desc.style.color = "red";
    CHECK_STATUS(
        neeh_stroke_create(&invalid_stroke_desc, &invalid_stroke),
        NEEH_STATUS_INVALID_ARGUMENT);
    CHECK(invalid_stroke == NULL);

    neeh_stroke_info_t stroke_info;
    CHECK_STATUS(neeh_stroke_get_info(stroke, &stroke_info), NEEH_STATUS_OK);
    CHECK(stroke_info.author == NEEH_AUTHOR_AGENT);
    CHECK(stroke_info.created_at_ms == 123456);
    CHECK(stroke_info.point_count == 3);
    CHECK(stroke_info.width == 3.0);

    neeh_bbox_t stroke_box;
    CHECK_STATUS(neeh_stroke_get_bbox(stroke, &stroke_box), NEEH_STATUS_OK);
    CHECK(stroke_box.min_x == 2.0 && stroke_box.max_y == 15.0);
    int64_t duration = 0;
    CHECK_STATUS(neeh_stroke_get_duration_ms(stroke, &duration), NEEH_STATUS_OK);
    CHECK(duration == 30);
    neeh_point_t copied_point;
    CHECK_STATUS(neeh_stroke_get_point(stroke, 1, &copied_point), NEEH_STATUS_OK);
    CHECK(copied_point.pressure == 0.75F && copied_point.tilt_y == -6.0F);
    CHECK_STATUS(neeh_stroke_get_point(stroke, 9, &copied_point), NEEH_STATUS_OUT_OF_RANGE);
    CHECK(strlen(neeh_last_error_message()) > 0);
    char preserved_error[128];
    snprintf(preserved_error, sizeof(preserved_error), "%s", neeh_last_error_message());
    neeh_stroke_destroy(NULL);
    (void)neeh_abi_version();
    (void)neeh_status_name(NEEH_STATUS_OK);
    (void)neeh_stroke_style_default();
    CHECK(strcmp(neeh_last_error_message(), preserved_error) == 0);

    CHECK_STATUS(neeh_stroke_translate(stroke, 100.0, -1.0, &translated), NEEH_STATUS_OK);
    CHECK_STATUS(neeh_stroke_clone(stroke, &cloned), NEEH_STATUS_OK);
    char original_id[64];
    char translated_id[64];
    copy_stroke_id(stroke, original_id, sizeof(original_id));
    copy_stroke_id(translated, translated_id, sizeof(translated_id));
    CHECK(strcmp(original_id, translated_id) == 0);
    copy_stroke_id(cloned, translated_id, sizeof(translated_id));
    CHECK(strcmp(original_id, translated_id) == 0);
    CHECK_STATUS(neeh_stroke_get_bbox(translated, &stroke_box), NEEH_STATUS_OK);
    CHECK(stroke_box.min_x == 102.0 && stroke_box.min_y == 2.0);

    size_t required = 0;
    char tiny[2];
    CHECK_STATUS(neeh_stroke_copy_id(stroke, NULL, 0, &required), NEEH_STATUS_OK);
    CHECK(required == strlen("st_c_abi") + 1);
    CHECK_STATUS(neeh_stroke_copy_color(stroke, NULL, 0, &required), NEEH_STATUS_OK);
    CHECK(required == strlen("#336699") + 1);
    CHECK_STATUS(
        neeh_stroke_copy_id(stroke, tiny, sizeof(tiny), &required),
        NEEH_STATUS_BUFFER_TOO_SMALL);
    CHECK(required == strlen("st_c_abi") + 1);

    neeh_document_desc_t document_desc = neeh_document_desc_default();
    document_desc.title = "C ABI document";
    document_desc.id = "doc_c_abi";
    document_desc.created_at_ms = 99;

    neeh_document_desc_t blank_document_desc = document_desc;
    blank_document_desc.id = "   ";
    neeh_document_t* blank_document = NULL;
    CHECK_STATUS(
        neeh_document_create(&blank_document_desc, &blank_document),
        NEEH_STATUS_INVALID_ARGUMENT);
    CHECK(blank_document == NULL);

    CHECK_STATUS(neeh_document_create(&document_desc, &document), NEEH_STATUS_OK);
    char copied_text[64];
    CHECK_STATUS(neeh_document_copy_id(document, NULL, 0, &required), NEEH_STATUS_OK);
    CHECK(required == strlen("doc_c_abi") + 1);
    CHECK_STATUS(
        neeh_document_copy_id(document, copied_text, sizeof(copied_text), &required),
        NEEH_STATUS_OK);
    CHECK(strcmp(copied_text, "doc_c_abi") == 0);
    CHECK_STATUS(neeh_document_set_title(document, "Renamed"), NEEH_STATUS_OK);
    CHECK_STATUS(
        neeh_document_copy_title(document, copied_text, sizeof(copied_text), &required),
        NEEH_STATUS_OK);
    CHECK(strcmp(copied_text, "Renamed") == 0);
    int64_t document_time = 0;
    CHECK_STATUS(
        neeh_document_get_created_at_ms(document, &document_time),
        NEEH_STATUS_OK);
    CHECK(document_time == 99);
    size_t page_count = 0;
    CHECK_STATUS(neeh_document_get_page_count(document, &page_count), NEEH_STATUS_OK);
    CHECK(page_count == 1);

    neeh_page_info_t page_info;
    CHECK_STATUS(neeh_document_get_page_info(document, 0, &page_info), NEEH_STATUS_OK);
    CHECK(page_info.width == 1000.0 && page_info.height == 1414.0);
    CHECK(page_info.layer_count == 1);

    neeh_page_desc_t invalid_page_desc = neeh_page_desc_default();
    invalid_page_desc.id = "";
    CHECK_STATUS(
        neeh_document_add_page(document, &invalid_page_desc, NULL),
        NEEH_STATUS_INVALID_ARGUMENT);
    invalid_page_desc.id = "pg_invalid_color";
    invalid_page_desc.background = "white";
    CHECK_STATUS(
        neeh_document_add_page(document, &invalid_page_desc, NULL),
        NEEH_STATUS_INVALID_ARGUMENT);

    neeh_page_desc_t second_page_desc = neeh_page_desc_default();
    second_page_desc.width = 320.0;
    second_page_desc.height = 240.0;
    second_page_desc.background = "#abc";
    second_page_desc.id = "pg_second";
    second_page_desc.create_default_layer = 0;
    size_t second_page = 0;
    CHECK_STATUS(
        neeh_document_add_page(document, &second_page_desc, &second_page),
        NEEH_STATUS_OK);
    CHECK(second_page == 1);
    CHECK_STATUS(neeh_document_get_page_count(document, &page_count), NEEH_STATUS_OK);
    CHECK(page_count == 2);
    CHECK_STATUS(neeh_document_get_page_info(document, second_page, &page_info), NEEH_STATUS_OK);
    CHECK(page_info.width == 320.0 && page_info.layer_count == 0);
    CHECK_STATUS(
        neeh_document_copy_page_background(
            document,
            second_page,
            copied_text,
            sizeof(copied_text),
            &required),
        NEEH_STATUS_OK);
    CHECK(strcmp(copied_text, "#abc") == 0);
    CHECK_STATUS(
        neeh_document_copy_page_id(
            document,
            second_page,
            copied_text,
            sizeof(copied_text),
            &required),
        NEEH_STATUS_OK);
    CHECK(strcmp(copied_text, "pg_second") == 0);

    neeh_layer_desc_t extra_layer_desc = neeh_layer_desc_default();
    extra_layer_desc.name = "answers";
    extra_layer_desc.author = NEEH_AUTHOR_AGENT;
    extra_layer_desc.id = "ly_answers";
    size_t extra_layer = 99;
    neeh_layer_desc_t invalid_layer_desc = neeh_layer_desc_default();
    invalid_layer_desc.name = "";
    CHECK_STATUS(
        neeh_page_add_layer(document, second_page, &invalid_layer_desc, NULL),
        NEEH_STATUS_INVALID_ARGUMENT);
    invalid_layer_desc.name = "ink";
    invalid_layer_desc.id = "\n ";
    CHECK_STATUS(
        neeh_page_add_layer(document, second_page, &invalid_layer_desc, NULL),
        NEEH_STATUS_INVALID_ARGUMENT);
    CHECK_STATUS(
        neeh_page_add_layer(document, second_page, &extra_layer_desc, &extra_layer),
        NEEH_STATUS_OK);
    CHECK(extra_layer == 0);
    CHECK_STATUS(
        neeh_page_copy_layer_name(
            document,
            second_page,
            extra_layer,
            copied_text,
            sizeof(copied_text),
            &required),
        NEEH_STATUS_OK);
    CHECK(strcmp(copied_text, "answers") == 0);
    CHECK_STATUS(
        neeh_page_copy_layer_id(
            document,
            second_page,
            extra_layer,
            copied_text,
            sizeof(copied_text),
            &required),
        NEEH_STATUS_OK);
    CHECK(strcmp(copied_text, "ly_answers") == 0);
    CHECK_STATUS(neeh_layer_set_locked(document, second_page, extra_layer, 1), NEEH_STATUS_OK);
    CHECK_STATUS(
        neeh_page_remove_layer(document, second_page, extra_layer),
        NEEH_STATUS_LOCKED);
    CHECK_STATUS(neeh_layer_set_locked(document, second_page, extra_layer, 0), NEEH_STATUS_OK);
    CHECK_STATUS(neeh_page_remove_layer(document, second_page, extra_layer), NEEH_STATUS_OK);
    CHECK_STATUS(neeh_document_remove_page(document, second_page), NEEH_STATUS_OK);
    CHECK_STATUS(neeh_document_get_page_count(document, &page_count), NEEH_STATUS_OK);
    CHECK(page_count == 1);

    size_t agent_layer = 99;
    CHECK_STATUS(
        neeh_page_add_stroke(document, 0, stroke, NULL, &agent_layer),
        NEEH_STATUS_OK);
    CHECK(agent_layer == 1);
    CHECK_STATUS(neeh_document_get_page_info(document, 0, &page_info), NEEH_STATUS_OK);
    CHECK(page_info.layer_count == 2);

    neeh_layer_info_t layer_info;
    CHECK_STATUS(neeh_page_get_layer_info(document, 0, agent_layer, &layer_info), NEEH_STATUS_OK);
    CHECK(layer_info.author == NEEH_AUTHOR_AGENT);
    CHECK(layer_info.stroke_count == 1);

    CHECK_STATUS(
        neeh_layer_add_stroke(document, 0, agent_layer, stroke),
        NEEH_STATUS_CONFLICT);
    CHECK_STATUS(neeh_layer_set_locked(document, 0, agent_layer, 1), NEEH_STATUS_OK);
    CHECK_STATUS(
        neeh_page_translate_stroke(document, 0, "st_c_abi", 1.0, 1.0),
        NEEH_STATUS_LOCKED);
    CHECK(strstr(neeh_last_error_message(), "locked") != NULL);
    CHECK_STATUS(neeh_layer_set_locked(document, 0, agent_layer, 0), NEEH_STATUS_OK);
    CHECK_STATUS(
        neeh_page_translate_stroke(document, 0, "st_c_abi", 1.0, 1.0),
        NEEH_STATUS_OK);

    neeh_stroke_style_t highlighter = neeh_stroke_style_highlighter("#ffff00", 10.0);
    CHECK_STATUS(
        neeh_page_restyle_stroke(document, 0, "st_c_abi", &highlighter),
        NEEH_STATUS_OK);

    neeh_bbox_t region = {0.0, 0.0, 20.0, 20.0};
    CHECK_STATUS(neeh_page_query_region(document, 0, &region, 1, &list), NEEH_STATUS_OK);
    size_t list_count = 0;
    CHECK_STATUS(neeh_stroke_list_get_count(list, &list_count), NEEH_STATUS_OK);
    CHECK(list_count == 1);
    CHECK_STATUS(neeh_stroke_list_get(list, 0, &snapshot_stroke), NEEH_STATUS_OK);
    copy_stroke_id(snapshot_stroke, translated_id, sizeof(translated_id));
    CHECK(strcmp(translated_id, "st_c_abi") == 0);

    neeh_stroke_list_t* time_list = NULL;
    CHECK_STATUS(
        neeh_page_query_since(document, 0, -1, &time_list),
        NEEH_STATUS_INVALID_ARGUMENT);
    CHECK(time_list == NULL);
    CHECK_STATUS(neeh_page_query_since(document, 0, 123456, &time_list), NEEH_STATUS_OK);
    CHECK_STATUS(neeh_stroke_list_get_count(time_list, &list_count), NEEH_STATUS_OK);
    CHECK(list_count == 1);
    neeh_stroke_list_destroy(time_list);

    neeh_stroke_list_t* visible_list = NULL;
    CHECK_STATUS(neeh_layer_set_visible(document, 0, agent_layer, 0), NEEH_STATUS_OK);
    CHECK_STATUS(neeh_page_list_strokes(document, 0, 1, &visible_list), NEEH_STATUS_OK);
    CHECK_STATUS(neeh_stroke_list_get_count(visible_list, &list_count), NEEH_STATUS_OK);
    CHECK(list_count == 0);
    neeh_stroke_list_destroy(visible_list);
    CHECK_STATUS(neeh_layer_set_visible(document, 0, agent_layer, 1), NEEH_STATUS_OK);

    CHECK_STATUS(neeh_document_render_page_svg(document, 0, NULL, 1.0, &svg), NEEH_STATUS_OK);
    CHECK(svg != NULL);
    CHECK(neeh_string_size(svg) > 50);
    CHECK(strstr(neeh_string_data(svg), "<polyline") != NULL);
    CHECK(strstr(neeh_string_data(svg), "opacity=\"0.35\"") != NULL);

    CHECK_STATUS(
        neeh_document_render_page_rgba(document, 0, &region, 64, 64, &image),
        NEEH_STATUS_OK);
    CHECK(neeh_image_width(image) == 64);
    CHECK(neeh_image_height(image) == 64);
    CHECK(neeh_image_stride(image) == 256);
    CHECK(neeh_image_size(image) == 64 * 64 * 4);
    CHECK(neeh_image_data(image) != NULL);

    CHECK_STATUS(
        neeh_page_find_stroke(document, 0, "missing_for_error_lifetime", &agent_layer, &list_count),
        NEEH_STATUS_NOT_FOUND);
    snprintf(preserved_error, sizeof(preserved_error), "%s", neeh_last_error_message());
    CHECK(neeh_image_width(image) == 64);
    CHECK(neeh_image_data(image) != NULL);
    CHECK(neeh_string_size(svg) > 0);
    CHECK(neeh_string_data(svg) != NULL);
    neeh_image_destroy(NULL);
    neeh_string_destroy(NULL);
    CHECK(strcmp(neeh_last_error_message(), preserved_error) == 0);

    neeh_bbox_t inverted = {10.0, 10.0, 0.0, 0.0};
    neeh_stroke_list_t* invalid_list = NULL;
    CHECK_STATUS(
        neeh_page_query_region(document, 0, &inverted, 0, &invalid_list),
        NEEH_STATUS_INVALID_ARGUMENT);
    CHECK(invalid_list == NULL);

    CHECK_STATUS(
        neeh_page_remove_stroke(document, 0, "st_c_abi", &removed),
        NEEH_STATUS_OK);
    CHECK(removed != NULL);
    CHECK_STATUS(
        neeh_page_find_stroke(document, 0, "st_c_abi", &agent_layer, &list_count),
        NEEH_STATUS_NOT_FOUND);
    /* The earlier list and its child handle are snapshots and survive removal. */
    CHECK_STATUS(neeh_stroke_get_info(snapshot_stroke, &stroke_info), NEEH_STATUS_OK);
    CHECK(stroke_info.point_count == 3);

    /* --- ink-analysis parity over the C ABI --- */
    CHECK(strcmp(neeh_direction_name(NEEH_DIRECTION_DOWN_RIGHT), "down-right") == 0);
    CHECK(strcmp(
        neeh_direction_name(NEEH_DIRECTION_CLOSED_OR_STATIONARY),
        "closed-or-stationary") == 0);

    neeh_mark_analysis_t analysis;
    CHECK_STATUS(neeh_stroke_analyze(stroke, 1000.0, 1414.0, &analysis), NEEH_STATUS_OK);
    CHECK(analysis.start_ms == 123456 + 10);
    CHECK(analysis.end_ms == 123456 + 40);
    CHECK(analysis.upper_half == 1);
    CHECK(analysis.left_half == 1);
    CHECK(analysis.direction == NEEH_DIRECTION_DOWN_RIGHT);
    CHECK(analysis.pressure_min == 0.25 && analysis.pressure_max == 1.0);
    CHECK_STATUS(neeh_stroke_analyze(stroke, 0.0, 1414.0, &analysis),
                 NEEH_STATUS_INVALID_ARGUMENT);
    CHECK_STATUS(neeh_stroke_analyze(NULL, 1000.0, 1414.0, &analysis),
                 NEEH_STATUS_INVALID_ARGUMENT);

    /* Page 0 has no visible strokes left here (st_c_abi was removed above),
     * so the empty page is a clean negative probe. */
    neeh_mark_analysis_t latest_analysis;
    CHECK_STATUS(neeh_page_latest_mark(document, 0, &latest_analysis, NULL),
                 NEEH_STATUS_NOT_FOUND);
    CHECK_STATUS(neeh_page_latest_mark(document, 0, NULL, NULL),
                 NEEH_STATUS_INVALID_ARGUMENT);
    CHECK_STATUS(neeh_page_latest_mark(document, 99, &latest_analysis, NULL),
                 NEEH_STATUS_OUT_OF_RANGE);

    /* Add two timed strokes, then check the temporal analyzers end to end. */
    neeh_point_t early_points[2] = {
        {100.0, 100.0, 0, 0.4F, 0.0F, 0.0F},
        {112.0, 104.0, 100, 0.8F, 0.0F, 0.0F},
    };
    neeh_point_t late_points[2] = {
        {300.0, 1200.0, 0, 0.4F, 0.0F, 0.0F},
        {312.0, 1204.0, 100, 0.8F, 0.0F, 0.0F},
    };
    neeh_stroke_desc_t early_desc = stroke_desc;
    early_desc.points = early_points;
    early_desc.point_count = 2;
    early_desc.id = "st_early";
    early_desc.author = NEEH_AUTHOR_USER;
    early_desc.created_at_ms = 1000;
    neeh_stroke_desc_t late_desc = early_desc;
    late_desc.points = late_points;
    late_desc.id = "st_late";
    late_desc.created_at_ms = 2000;

    neeh_stroke_t* early_stroke = NULL;
    neeh_stroke_t* late_stroke = NULL;
    CHECK_STATUS(neeh_stroke_create(&early_desc, &early_stroke), NEEH_STATUS_OK);
    CHECK_STATUS(neeh_stroke_create(&late_desc, &late_stroke), NEEH_STATUS_OK);
    CHECK_STATUS(neeh_page_add_stroke(document, 0, early_stroke, "ink", NULL), NEEH_STATUS_OK);
    CHECK_STATUS(neeh_page_add_stroke(document, 0, late_stroke, "ink", NULL), NEEH_STATUS_OK);

    /* latest mark: analysis record plus an owned handle for the stroke. */
    neeh_stroke_t* latest_stroke = NULL;
    CHECK_STATUS(
        neeh_page_latest_mark(document, 0, &latest_analysis, &latest_stroke),
        NEEH_STATUS_OK);
    CHECK(latest_stroke != NULL);
    CHECK(latest_analysis.start_ms == 2000);
    CHECK(latest_analysis.end_ms == 2100);
    CHECK(latest_analysis.upper_half == 0); /* y ~1202 on a 1414-tall page */
    char latest_id[64];
    copy_stroke_id(latest_stroke, latest_id, sizeof latest_id);
    CHECK(strcmp(latest_id, "st_late") == 0);

    /* creation order: chronological snapshot list, earliest first. */
    neeh_stroke_list_t* chrono = NULL;
    CHECK_STATUS(neeh_page_creation_order(document, 0, &chrono), NEEH_STATUS_OK);
    size_t chrono_count = 0;
    CHECK_STATUS(neeh_stroke_list_get_count(chrono, &chrono_count), NEEH_STATUS_OK);
    CHECK(chrono_count == 2);
    neeh_stroke_t* first = NULL;
    CHECK_STATUS(neeh_stroke_list_get(chrono, 0, &first), NEEH_STATUS_OK);
    char first_id[64];
    copy_stroke_id(first, first_id, sizeof first_id);
    CHECK(strcmp(first_id, "st_early") == 0);
    neeh_stroke_destroy(first);
    neeh_stroke_list_destroy(chrono);
    neeh_stroke_destroy(latest_stroke);
    neeh_stroke_destroy(late_stroke);
    neeh_stroke_destroy(early_stroke);

    neeh_image_destroy(image);
    neeh_string_destroy(svg);
    neeh_stroke_destroy(removed);
    neeh_stroke_destroy(snapshot_stroke);
    neeh_stroke_list_destroy(list);
    neeh_document_destroy(document);
    neeh_stroke_destroy(translated);
    neeh_stroke_destroy(cloned);
    neeh_stroke_destroy(stroke);

    if (failures != 0) {
        fprintf(stderr, "%d C ABI check(s) failed\n", failures);
        return EXIT_FAILURE;
    }
    puts("portable C ABI checks passed");
    return EXIT_SUCCESS;
}
