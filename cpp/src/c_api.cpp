#include <neeh/c_api.h>

#include <neeh/analysis.hpp>
#include <neeh/core.hpp>
#include <neeh/render.hpp>

#include <algorithm>
#include <cstring>
#include <memory>
#include <new>
#include <optional>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

struct neeh_document {
    neeh::Document value;
};

struct neeh_stroke {
    neeh::Stroke value;
};

struct neeh_stroke_list {
    std::vector<neeh::Stroke> values;
};

struct neeh_string {
    std::string value;
};

struct neeh_image {
    neeh::Image value;
};

namespace {

thread_local std::string last_error;

neeh_status_t status_from_error(neeh::ErrorCode code) noexcept {
    switch (code) {
    case neeh::ErrorCode::ok: return NEEH_STATUS_OK;
    case neeh::ErrorCode::invalid_argument: return NEEH_STATUS_INVALID_ARGUMENT;
    case neeh::ErrorCode::out_of_range: return NEEH_STATUS_OUT_OF_RANGE;
    case neeh::ErrorCode::not_found: return NEEH_STATUS_NOT_FOUND;
    case neeh::ErrorCode::locked: return NEEH_STATUS_LOCKED;
    case neeh::ErrorCode::conflict: return NEEH_STATUS_CONFLICT;
    case neeh::ErrorCode::buffer_too_small: return NEEH_STATUS_BUFFER_TOO_SMALL;
    case neeh::ErrorCode::out_of_memory: return NEEH_STATUS_OUT_OF_MEMORY;
    case neeh::ErrorCode::internal: return NEEH_STATUS_INTERNAL;
    }
    return NEEH_STATUS_INTERNAL;
}

void record_error(const char* message) noexcept {
    try {
        last_error = message == nullptr ? "" : message;
    } catch (...) {
        last_error.clear();
    }
}

template <typename Function>
neeh_status_t invoke(Function&& function) noexcept {
    last_error.clear();
    try {
        function();
        return NEEH_STATUS_OK;
    } catch (const neeh::Error& error) {
        record_error(error.what());
        return status_from_error(error.code());
    } catch (const std::invalid_argument& error) {
        record_error(error.what());
        return NEEH_STATUS_INVALID_ARGUMENT;
    } catch (const std::out_of_range& error) {
        record_error(error.what());
        return NEEH_STATUS_OUT_OF_RANGE;
    } catch (const std::bad_alloc&) {
        record_error("allocation failed");
        return NEEH_STATUS_OUT_OF_MEMORY;
    } catch (const std::exception& error) {
        record_error(error.what());
        return NEEH_STATUS_INTERNAL;
    } catch (...) {
        record_error("unknown internal error");
        return NEEH_STATUS_INTERNAL;
    }
}

void require(bool condition, const char* message) {
    if (!condition) {
        throw neeh::Error(neeh::ErrorCode::invalid_argument, message);
    }
}

neeh::Author author_from_c(neeh_author_t author) {
    switch (author) {
    case NEEH_AUTHOR_USER: return neeh::Author::user;
    case NEEH_AUTHOR_AGENT: return neeh::Author::agent;
    }
    throw neeh::Error(neeh::ErrorCode::invalid_argument, "unknown C ABI author");
}

neeh_author_t author_to_c(neeh::Author author) {
    return author == neeh::Author::agent ? NEEH_AUTHOR_AGENT : NEEH_AUTHOR_USER;
}

neeh::Brush brush_from_c(neeh_brush_t brush) {
    switch (brush) {
    case NEEH_BRUSH_PEN: return neeh::Brush::pen;
    case NEEH_BRUSH_MARKER: return neeh::Brush::marker;
    case NEEH_BRUSH_HIGHLIGHTER: return neeh::Brush::highlighter;
    }
    throw neeh::Error(neeh::ErrorCode::invalid_argument, "unknown C ABI brush");
}

neeh_brush_t brush_to_c(neeh::Brush brush) {
    switch (brush) {
    case neeh::Brush::pen: return NEEH_BRUSH_PEN;
    case neeh::Brush::marker: return NEEH_BRUSH_MARKER;
    case neeh::Brush::highlighter: return NEEH_BRUSH_HIGHLIGHTER;
    }
    return NEEH_BRUSH_PEN;
}

neeh::StrokeStyle style_from_c(const neeh_stroke_style_t& style) {
    return neeh::StrokeStyle(
        style.color == nullptr ? "#1a1a1a" : style.color,
        style.width,
        brush_from_c(style.brush),
        style.opacity);
}

neeh::BoundingBox bbox_from_c(const neeh_bbox_t& box) {
    return neeh::BoundingBox(box.min_x, box.min_y, box.max_x, box.max_y);
}

neeh_bbox_t bbox_to_c(const neeh::BoundingBox& box) {
    return neeh_bbox_t {box.min_x(), box.min_y(), box.max_x(), box.max_y()};
}

neeh_mark_analysis_t mark_analysis_to_c(const neeh::analysis::MarkAnalysis& analysis) {
    neeh_mark_analysis_t out;
    out.bbox = bbox_to_c(analysis.bbox);
    out.center_x = analysis.center_x;
    out.center_y = analysis.center_y;
    out.start_ms = analysis.start_ms;
    out.end_ms = analysis.end_ms;
    out.duration_ms = analysis.duration_ms;
    out.upper_half = analysis.upper_half ? 1 : 0;
    out.left_half = analysis.left_half ? 1 : 0;
    out.direction = static_cast<neeh_direction_t>(analysis.direction);
    out.path_length = analysis.path_length;
    out.pressure_mean = analysis.pressure_mean;
    out.pressure_min = analysis.pressure_min;
    out.pressure_max = analysis.pressure_max;
    return out;
}

neeh_point_t point_to_c(const neeh::Point& point) {
    return neeh_point_t {
        point.x,
        point.y,
        point.t_ms,
        point.pressure,
        point.tilt_x,
        point.tilt_y};
}

neeh::Point point_from_c(const neeh_point_t& point) {
    return neeh::Point {
        point.x,
        point.y,
        point.t_ms,
        point.pressure,
        point.tilt_x,
        point.tilt_y};
}

std::optional<std::string> optional_id(const char* value) {
    return value == nullptr ? std::nullopt : std::optional<std::string>(value);
}

neeh::Page& page_at(neeh_document_t* document, size_t index) {
    require(document != nullptr, "document handle is NULL");
    auto* page = document->value.page(index);
    if (page == nullptr) {
        throw neeh::Error(neeh::ErrorCode::out_of_range, "page index is out of range");
    }
    return *page;
}

const neeh::Page& page_at(const neeh_document_t* document, size_t index) {
    require(document != nullptr, "document handle is NULL");
    const auto* page = document->value.page(index);
    if (page == nullptr) {
        throw neeh::Error(neeh::ErrorCode::out_of_range, "page index is out of range");
    }
    return *page;
}

neeh::Layer& layer_at(neeh_document_t* document, size_t page_index, size_t layer_index) {
    auto& page = page_at(document, page_index);
    auto* layer = page.layer(layer_index);
    if (layer == nullptr) {
        throw neeh::Error(neeh::ErrorCode::out_of_range, "layer index is out of range");
    }
    return *layer;
}

const neeh::Layer& layer_at(
    const neeh_document_t* document,
    size_t page_index,
    size_t layer_index) {
    const auto& page = page_at(document, page_index);
    const auto* layer = page.layer(layer_index);
    if (layer == nullptr) {
        throw neeh::Error(neeh::ErrorCode::out_of_range, "layer index is out of range");
    }
    return *layer;
}

void copy_string(
    const std::string& value,
    char* buffer,
    size_t capacity,
    size_t* out_required_size) {
    require(out_required_size != nullptr, "out_required_size is NULL");
    const size_t required = value.size() + 1;
    *out_required_size = required;
    if (buffer == nullptr) {
        return;
    }
    if (capacity < required) {
        throw neeh::Error(neeh::ErrorCode::buffer_too_small, "string buffer is too small");
    }
    std::memcpy(buffer, value.c_str(), required);
}

std::vector<neeh::Stroke> snapshot(const std::vector<const neeh::Stroke*>& strokes) {
    std::vector<neeh::Stroke> values;
    values.reserve(strokes.size());
    for (const auto* stroke : strokes) {
        values.push_back(*stroke);
    }
    return values;
}

} // namespace

extern "C" {

uint32_t neeh_abi_version(void) {
    return NEEH_ABI_VERSION;
}

const char* neeh_status_name(neeh_status_t status) {
    switch (status) {
    case NEEH_STATUS_OK: return "ok";
    case NEEH_STATUS_INVALID_ARGUMENT: return "invalid_argument";
    case NEEH_STATUS_OUT_OF_RANGE: return "out_of_range";
    case NEEH_STATUS_NOT_FOUND: return "not_found";
    case NEEH_STATUS_LOCKED: return "locked";
    case NEEH_STATUS_CONFLICT: return "conflict";
    case NEEH_STATUS_BUFFER_TOO_SMALL: return "buffer_too_small";
    case NEEH_STATUS_OUT_OF_MEMORY: return "out_of_memory";
    case NEEH_STATUS_INTERNAL: return "internal";
    }
    return "unknown";
}

const char* neeh_last_error_message(void) {
    return last_error.c_str();
}

neeh_stroke_style_t neeh_stroke_style_default(void) {
    return neeh_stroke_style_t {"#1a1a1a", 2.0, NEEH_BRUSH_PEN, 1.0};
}

neeh_stroke_style_t neeh_stroke_style_highlighter(const char* color, double width) {
    return neeh_stroke_style_t {
        color == nullptr ? "#ffe066" : color,
        width,
        NEEH_BRUSH_HIGHLIGHTER,
        0.35};
}

neeh_document_desc_t neeh_document_desc_default(void) {
    return neeh_document_desc_t {"Untitled", nullptr, INT64_MIN, 1};
}

neeh_page_desc_t neeh_page_desc_default(void) {
    return neeh_page_desc_t {1000.0, 1414.0, "#ffffff", nullptr, 1};
}

neeh_layer_desc_t neeh_layer_desc_default(void) {
    return neeh_layer_desc_t {"ink", NEEH_AUTHOR_USER, nullptr, 1, 0};
}

neeh_status_t neeh_stroke_create(const neeh_stroke_desc_t* desc, neeh_stroke_t** out_stroke) {
    return invoke([&] {
        require(desc != nullptr, "stroke descriptor is NULL");
        require(out_stroke != nullptr, "out_stroke is NULL");
        *out_stroke = nullptr;
        require(desc->points != nullptr || desc->point_count == 0, "stroke points are NULL");
        std::vector<neeh::Point> points;
        points.reserve(desc->point_count);
        for (size_t index = 0; index < desc->point_count; ++index) {
            points.push_back(point_from_c(desc->points[index]));
        }
        auto* created = new neeh_stroke {
            neeh::Stroke(
                std::move(points),
                style_from_c(desc->style),
                optional_id(desc->id),
                author_from_c(desc->author),
                desc->created_at_ms)};
        *out_stroke = created;
    });
}

void neeh_stroke_destroy(neeh_stroke_t* stroke) {
    delete stroke;
}

neeh_status_t neeh_stroke_clone(const neeh_stroke_t* stroke, neeh_stroke_t** out_stroke) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        require(out_stroke != nullptr, "out_stroke is NULL");
        *out_stroke = nullptr;
        *out_stroke = new neeh_stroke {stroke->value};
    });
}

neeh_status_t neeh_stroke_translate(
    const neeh_stroke_t* stroke,
    double dx,
    double dy,
    neeh_stroke_t** out_stroke) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        require(out_stroke != nullptr, "out_stroke is NULL");
        *out_stroke = nullptr;
        *out_stroke = new neeh_stroke {stroke->value.translated(dx, dy)};
    });
}

neeh_status_t neeh_stroke_get_info(const neeh_stroke_t* stroke, neeh_stroke_info_t* out_info) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        require(out_info != nullptr, "out_info is NULL");
        const auto& value = stroke->value;
        *out_info = neeh_stroke_info_t {
            author_to_c(value.author()),
            value.created_at_ms(),
            value.points().size(),
            value.style().width(),
            brush_to_c(value.style().brush()),
            value.style().opacity()};
    });
}

neeh_status_t neeh_stroke_get_bbox(const neeh_stroke_t* stroke, neeh_bbox_t* out_bbox) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        require(out_bbox != nullptr, "out_bbox is NULL");
        *out_bbox = bbox_to_c(stroke->value.bbox());
    });
}

neeh_status_t neeh_stroke_get_duration_ms(
    const neeh_stroke_t* stroke,
    int64_t* out_duration_ms) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        require(out_duration_ms != nullptr, "out_duration_ms is NULL");
        *out_duration_ms = stroke->value.duration_ms();
    });
}

neeh_status_t neeh_stroke_get_point(
    const neeh_stroke_t* stroke,
    size_t index,
    neeh_point_t* out_point) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        require(out_point != nullptr, "out_point is NULL");
        if (index >= stroke->value.points().size()) {
            throw neeh::Error(neeh::ErrorCode::out_of_range, "point index is out of range");
        }
        *out_point = point_to_c(stroke->value.points()[index]);
    });
}

neeh_status_t neeh_stroke_copy_id(
    const neeh_stroke_t* stroke,
    char* buffer,
    size_t capacity,
    size_t* out_required_size) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        copy_string(stroke->value.id(), buffer, capacity, out_required_size);
    });
}

neeh_status_t neeh_stroke_copy_color(
    const neeh_stroke_t* stroke,
    char* buffer,
    size_t capacity,
    size_t* out_required_size) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        copy_string(stroke->value.style().color(), buffer, capacity, out_required_size);
    });
}

neeh_status_t neeh_document_create(
    const neeh_document_desc_t* desc,
    neeh_document_t** out_document) {
    return invoke([&] {
        require(out_document != nullptr, "out_document is NULL");
        *out_document = nullptr;
        const neeh_document_desc_t defaults = neeh_document_desc_default();
        const auto& value = desc == nullptr ? defaults : *desc;
        *out_document = new neeh_document {
            neeh::Document(
                value.title == nullptr ? "Untitled" : value.title,
                optional_id(value.id),
                value.created_at_ms,
                value.create_default_page != 0)};
    });
}

void neeh_document_destroy(neeh_document_t* document) {
    delete document;
}

neeh_status_t neeh_document_copy_id(
    const neeh_document_t* document,
    char* buffer,
    size_t capacity,
    size_t* out_required_size) {
    return invoke([&] {
        require(document != nullptr, "document handle is NULL");
        copy_string(document->value.id(), buffer, capacity, out_required_size);
    });
}

neeh_status_t neeh_document_copy_title(
    const neeh_document_t* document,
    char* buffer,
    size_t capacity,
    size_t* out_required_size) {
    return invoke([&] {
        require(document != nullptr, "document handle is NULL");
        copy_string(document->value.title(), buffer, capacity, out_required_size);
    });
}

neeh_status_t neeh_document_set_title(neeh_document_t* document, const char* title) {
    return invoke([&] {
        require(document != nullptr, "document handle is NULL");
        require(title != nullptr, "title is NULL");
        document->value.set_title(title);
    });
}

neeh_status_t neeh_document_get_created_at_ms(
    const neeh_document_t* document,
    int64_t* out_created_at_ms) {
    return invoke([&] {
        require(document != nullptr, "document handle is NULL");
        require(out_created_at_ms != nullptr, "out_created_at_ms is NULL");
        *out_created_at_ms = document->value.created_at_ms();
    });
}

neeh_status_t neeh_document_get_page_count(
    const neeh_document_t* document,
    size_t* out_count) {
    return invoke([&] {
        require(document != nullptr, "document handle is NULL");
        require(out_count != nullptr, "out_count is NULL");
        *out_count = document->value.pages().size();
    });
}

neeh_status_t neeh_document_add_page(
    neeh_document_t* document,
    const neeh_page_desc_t* desc,
    size_t* out_page_index) {
    return invoke([&] {
        require(document != nullptr, "document handle is NULL");
        const neeh_page_desc_t defaults = neeh_page_desc_default();
        const auto& value = desc == nullptr ? defaults : *desc;
        document->value.add_page(neeh::Page(
            value.width,
            value.height,
            value.background == nullptr ? "#ffffff" : value.background,
            optional_id(value.id),
            value.create_default_layer != 0));
        if (out_page_index != nullptr) {
            *out_page_index = document->value.pages().size() - 1;
        }
    });
}

neeh_status_t neeh_document_remove_page(neeh_document_t* document, size_t page_index) {
    return invoke([&] {
        require(document != nullptr, "document handle is NULL");
        if (!document->value.remove_page(page_index).has_value()) {
            throw neeh::Error(neeh::ErrorCode::out_of_range, "page index is out of range");
        }
    });
}

neeh_status_t neeh_document_get_page_info(
    const neeh_document_t* document,
    size_t page_index,
    neeh_page_info_t* out_info) {
    return invoke([&] {
        require(out_info != nullptr, "out_info is NULL");
        const auto& page = page_at(document, page_index);
        *out_info = neeh_page_info_t {page.width(), page.height(), page.layers().size()};
    });
}

neeh_status_t neeh_document_copy_page_id(
    const neeh_document_t* document,
    size_t page_index,
    char* buffer,
    size_t capacity,
    size_t* out_required_size) {
    return invoke([&] {
        copy_string(page_at(document, page_index).id(), buffer, capacity, out_required_size);
    });
}

neeh_status_t neeh_document_copy_page_background(
    const neeh_document_t* document,
    size_t page_index,
    char* buffer,
    size_t capacity,
    size_t* out_required_size) {
    return invoke([&] {
        copy_string(
            page_at(document, page_index).background(),
            buffer,
            capacity,
            out_required_size);
    });
}

neeh_status_t neeh_page_add_layer(
    neeh_document_t* document,
    size_t page_index,
    const neeh_layer_desc_t* desc,
    size_t* out_layer_index) {
    return invoke([&] {
        auto& page = page_at(document, page_index);
        const neeh_layer_desc_t defaults = neeh_layer_desc_default();
        const auto& value = desc == nullptr ? defaults : *desc;
        page.add_layer(neeh::Layer(
            value.name == nullptr ? "ink" : value.name,
            author_from_c(value.author),
            optional_id(value.id),
            value.visible != 0,
            value.locked != 0));
        if (out_layer_index != nullptr) {
            *out_layer_index = page.layers().size() - 1;
        }
    });
}

neeh_status_t neeh_page_remove_layer(
    neeh_document_t* document,
    size_t page_index,
    size_t layer_index) {
    return invoke([&] {
        auto& page = page_at(document, page_index);
        const auto* layer = page.layer(layer_index);
        if (layer == nullptr) {
            throw neeh::Error(neeh::ErrorCode::out_of_range, "layer index is out of range");
        }
        const std::string id = layer->id();
        if (!page.remove_layer(id).has_value()) {
            throw neeh::Error(neeh::ErrorCode::not_found, "layer was not found");
        }
    });
}

neeh_status_t neeh_page_get_layer_info(
    const neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    neeh_layer_info_t* out_info) {
    return invoke([&] {
        require(out_info != nullptr, "out_info is NULL");
        const auto& layer = layer_at(document, page_index, layer_index);
        *out_info = neeh_layer_info_t {
            author_to_c(layer.author()),
            static_cast<uint8_t>(layer.visible()),
            static_cast<uint8_t>(layer.locked()),
            layer.strokes().size()};
    });
}

neeh_status_t neeh_page_copy_layer_id(
    const neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    char* buffer,
    size_t capacity,
    size_t* out_required_size) {
    return invoke([&] {
        copy_string(
            layer_at(document, page_index, layer_index).id(),
            buffer,
            capacity,
            out_required_size);
    });
}

neeh_status_t neeh_page_copy_layer_name(
    const neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    char* buffer,
    size_t capacity,
    size_t* out_required_size) {
    return invoke([&] {
        copy_string(
            layer_at(document, page_index, layer_index).name(),
            buffer,
            capacity,
            out_required_size);
    });
}

neeh_status_t neeh_layer_set_visible(
    neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    uint8_t visible) {
    return invoke([&] { layer_at(document, page_index, layer_index).set_visible(visible != 0); });
}

neeh_status_t neeh_layer_set_locked(
    neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    uint8_t locked) {
    return invoke([&] { layer_at(document, page_index, layer_index).set_locked(locked != 0); });
}

neeh_status_t neeh_layer_add_stroke(
    neeh_document_t* document,
    size_t page_index,
    size_t layer_index,
    const neeh_stroke_t* stroke) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        auto& page = page_at(document, page_index);
        if (page.find(stroke->value.id()).has_value()) {
            throw neeh::Error(neeh::ErrorCode::conflict, "duplicate stroke id on page");
        }
        auto* layer = page.layer(layer_index);
        if (layer == nullptr) {
            throw neeh::Error(neeh::ErrorCode::out_of_range, "layer index is out of range");
        }
        layer->add(stroke->value);
    });
}

neeh_status_t neeh_page_add_stroke(
    neeh_document_t* document,
    size_t page_index,
    const neeh_stroke_t* stroke,
    const char* layer_key,
    size_t* out_layer_index) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        auto& page = page_at(document, page_index);
        page.add_stroke(stroke->value, layer_key == nullptr ? "" : layer_key);
        const auto location = page.find(stroke->value.id());
        if (!location.has_value()) {
            throw neeh::Error(neeh::ErrorCode::internal, "added stroke could not be found");
        }
        if (out_layer_index != nullptr) {
            *out_layer_index = location->layer_index;
        }
    });
}

neeh_status_t neeh_page_remove_stroke(
    neeh_document_t* document,
    size_t page_index,
    const char* stroke_id,
    neeh_stroke_t** out_removed) {
    return invoke([&] {
        require(stroke_id != nullptr, "stroke_id is NULL");
        if (out_removed != nullptr) {
            *out_removed = nullptr;
        }
        auto& page = page_at(document, page_index);
        const auto location = page.find(stroke_id);
        if (!location.has_value()) {
            throw neeh::Error(neeh::ErrorCode::not_found, "stroke was not found");
        }
        std::unique_ptr<neeh_stroke> pending;
        if (out_removed != nullptr) {
            pending = std::make_unique<neeh_stroke>(neeh_stroke {
                page.layers()[location->layer_index].strokes()[location->stroke_index]});
        }
        auto removed = page.remove_stroke(stroke_id);
        if (!removed.has_value()) {
            throw neeh::Error(neeh::ErrorCode::not_found, "stroke was not found");
        }
        if (out_removed != nullptr) {
            *out_removed = pending.release();
        }
    });
}

neeh_status_t neeh_page_translate_stroke(
    neeh_document_t* document,
    size_t page_index,
    const char* stroke_id,
    double dx,
    double dy) {
    return invoke([&] {
        require(stroke_id != nullptr, "stroke_id is NULL");
        page_at(document, page_index).translate_stroke(stroke_id, dx, dy);
    });
}

neeh_status_t neeh_page_restyle_stroke(
    neeh_document_t* document,
    size_t page_index,
    const char* stroke_id,
    const neeh_stroke_style_t* style) {
    return invoke([&] {
        require(stroke_id != nullptr, "stroke_id is NULL");
        require(style != nullptr, "style is NULL");
        page_at(document, page_index).restyle_stroke(stroke_id, style_from_c(*style));
    });
}

neeh_status_t neeh_page_find_stroke(
    const neeh_document_t* document,
    size_t page_index,
    const char* stroke_id,
    size_t* out_layer_index,
    size_t* out_stroke_index) {
    return invoke([&] {
        require(stroke_id != nullptr, "stroke_id is NULL");
        require(out_layer_index != nullptr, "out_layer_index is NULL");
        require(out_stroke_index != nullptr, "out_stroke_index is NULL");
        const auto location = page_at(document, page_index).find(stroke_id);
        if (!location.has_value()) {
            throw neeh::Error(neeh::ErrorCode::not_found, "stroke was not found");
        }
        *out_layer_index = location->layer_index;
        *out_stroke_index = location->stroke_index;
    });
}

neeh_status_t neeh_page_list_strokes(
    const neeh_document_t* document,
    size_t page_index,
    uint8_t visible_only,
    neeh_stroke_list_t** out_list) {
    return invoke([&] {
        require(out_list != nullptr, "out_list is NULL");
        *out_list = nullptr;
        *out_list = new neeh_stroke_list {
            snapshot(page_at(document, page_index).all_strokes(visible_only != 0))};
    });
}

neeh_status_t neeh_page_query_region(
    const neeh_document_t* document,
    size_t page_index,
    const neeh_bbox_t* region,
    uint8_t visible_only,
    neeh_stroke_list_t** out_list) {
    return invoke([&] {
        require(region != nullptr, "region is NULL");
        require(out_list != nullptr, "out_list is NULL");
        *out_list = nullptr;
        *out_list = new neeh_stroke_list {snapshot(
            page_at(document, page_index).strokes_in(
                bbox_from_c(*region),
                visible_only != 0))};
    });
}

neeh_status_t neeh_page_query_since(
    const neeh_document_t* document,
    size_t page_index,
    int64_t epoch_ms,
    neeh_stroke_list_t** out_list) {
    return invoke([&] {
        require(out_list != nullptr, "out_list is NULL");
        *out_list = nullptr;
        *out_list = new neeh_stroke_list {
            snapshot(page_at(document, page_index).strokes_since(epoch_ms))};
    });
}

void neeh_stroke_list_destroy(neeh_stroke_list_t* list) {
    delete list;
}

neeh_status_t neeh_stroke_list_get_count(
    const neeh_stroke_list_t* list,
    size_t* out_count) {
    return invoke([&] {
        require(list != nullptr, "stroke list handle is NULL");
        require(out_count != nullptr, "out_count is NULL");
        *out_count = list->values.size();
    });
}

neeh_status_t neeh_stroke_list_get(
    const neeh_stroke_list_t* list,
    size_t index,
    neeh_stroke_t** out_stroke) {
    return invoke([&] {
        require(list != nullptr, "stroke list handle is NULL");
        require(out_stroke != nullptr, "out_stroke is NULL");
        *out_stroke = nullptr;
        if (index >= list->values.size()) {
            throw neeh::Error(neeh::ErrorCode::out_of_range, "stroke list index is out of range");
        }
        *out_stroke = new neeh_stroke {list->values[index]};
    });
}

neeh_status_t neeh_document_render_page_svg(
    const neeh_document_t* document,
    size_t page_index,
    const neeh_bbox_t* region,
    double scale,
    neeh_string_t** out_svg) {
    return invoke([&] {
        require(out_svg != nullptr, "out_svg is NULL");
        *out_svg = nullptr;
        neeh::SvgRenderOptions options;
        options.scale = scale;
        if (region != nullptr) {
            options.region = bbox_from_c(*region);
        }
        *out_svg = new neeh_string {
            neeh::SvgRenderer {}.render(page_at(document, page_index), options)};
    });
}

void neeh_string_destroy(neeh_string_t* string_value) {
    delete string_value;
}

const char* neeh_string_data(const neeh_string_t* string_value) {
    return string_value == nullptr ? nullptr : string_value->value.data();
}

size_t neeh_string_size(const neeh_string_t* string_value) {
    return string_value == nullptr ? 0 : string_value->value.size();
}

neeh_status_t neeh_document_render_page_rgba(
    const neeh_document_t* document,
    size_t page_index,
    const neeh_bbox_t* region,
    uint32_t width,
    uint32_t height,
    neeh_image_t** out_image) {
    return invoke([&] {
        require(out_image != nullptr, "out_image is NULL");
        *out_image = nullptr;
        neeh::CpuRenderOptions options;
        options.width = width;
        options.height = height;
        if (region != nullptr) {
            options.region = bbox_from_c(*region);
        }
        *out_image = new neeh_image {
            neeh::CpuRenderer {}.render(page_at(document, page_index), options)};
    });
}

void neeh_image_destroy(neeh_image_t* image) {
    delete image;
}

const uint8_t* neeh_image_data(const neeh_image_t* image) {
    return image == nullptr ? nullptr : image->value.pixels().data();
}

size_t neeh_image_size(const neeh_image_t* image) {
    return image == nullptr ? 0 : image->value.pixels().size();
}

uint32_t neeh_image_width(const neeh_image_t* image) {
    return image == nullptr ? 0 : image->value.width();
}

uint32_t neeh_image_height(const neeh_image_t* image) {
    return image == nullptr ? 0 : image->value.height();
}

size_t neeh_image_stride(const neeh_image_t* image) {
    return image == nullptr ? 0 : image->value.stride();
}

const char* neeh_direction_name(neeh_direction_t direction) {
    return neeh::analysis::direction_name(
        static_cast<neeh::analysis::Direction>(direction));
}

neeh_status_t neeh_stroke_analyze(
    const neeh_stroke_t* stroke,
    double page_width,
    double page_height,
    neeh_mark_analysis_t* out_analysis) {
    return invoke([&] {
        require(stroke != nullptr, "stroke handle is NULL");
        require(out_analysis != nullptr, "out_analysis is NULL");
        require(page_width > 0.0 && page_height > 0.0, "page frame must be positive");
        *out_analysis = mark_analysis_to_c(
            neeh::analysis::analyze_stroke(stroke->value, page_width, page_height));
    });
}

neeh_status_t neeh_page_latest_mark(
    const neeh_document_t* document,
    size_t page_index,
    neeh_mark_analysis_t* out_analysis,
    neeh_stroke_t** out_stroke) {
    return invoke([&] {
        require(
            out_analysis != nullptr || out_stroke != nullptr,
            "at least one of out_analysis/out_stroke is required");
        if (out_stroke != nullptr) {
            *out_stroke = nullptr;
        }
        const auto& page = page_at(document, page_index);
        const auto latest = neeh::analysis::latest_mark(page);
        if (!latest) {
            throw neeh::Error(neeh::ErrorCode::not_found, "page has no visible strokes");
        }
        if (out_analysis != nullptr) {
            *out_analysis = mark_analysis_to_c(*latest);
        }
        if (out_stroke != nullptr) {
            for (const auto* stroke : page.all_strokes(true)) {
                if (stroke->id() == latest->id) {
                    *out_stroke = new neeh_stroke {*stroke};
                    return;
                }
            }
            throw neeh::Error(neeh::ErrorCode::internal, "latest mark disappeared");
        }
    });
}

neeh_status_t neeh_page_creation_order(
    const neeh_document_t* document,
    size_t page_index,
    neeh_stroke_list_t** out_list) {
    return invoke([&] {
        require(out_list != nullptr, "out_list is NULL");
        *out_list = nullptr;
        const auto& page = page_at(document, page_index);
        auto strokes = page.all_strokes(true);
        std::vector<size_t> order(strokes.size());
        for (size_t i = 0; i < strokes.size(); ++i) {
            order[i] = i;
        }
        auto key = [&strokes](size_t index) {
            const auto& stroke = *strokes[index];
            const auto start = stroke.created_at_ms() + stroke.points().front().t_ms;
            const auto end = stroke.created_at_ms() + stroke.points().back().t_ms;
            return std::make_tuple(start, end, index);
        };
        std::sort(order.begin(), order.end(), [&key](size_t a, size_t b) {
            return key(a) < key(b);
        });
        auto list = std::make_unique<neeh_stroke_list>();
        list->values.reserve(strokes.size());
        for (const auto index : order) {
            list->values.push_back(*strokes[index]);
        }
        *out_list = list.release();
    });
}

} // extern "C"
