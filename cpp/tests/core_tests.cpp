#include <neeh/core.hpp>
#include <neeh/render.hpp>

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

int failures = 0;

#define CHECK(condition)                                                                      \
    do {                                                                                      \
        if (!(condition)) {                                                                   \
            std::cerr << __FILE__ << ':' << __LINE__ << ": check failed: " << #condition      \
                      << '\n';                                                               \
            ++failures;                                                                       \
        }                                                                                     \
    } while (false)

template <typename Function>
void expect_error(neeh::ErrorCode expected, Function&& function) {
    try {
        function();
        CHECK(false);
    } catch (const neeh::Error& error) {
        CHECK(error.code() == expected);
        CHECK(std::string(error.what()).size() > 3);
    }
}

neeh::Stroke make_stroke(
    std::string id = "st_test",
    neeh::Author author = neeh::Author::user,
    std::int64_t created_at = 1000) {
    return neeh::Stroke(
        std::vector<neeh::Point> {
            {10.0, 20.0, 5, 0.5F, 10.0F, -20.0F},
            {30.0, 40.0, 25, 1.0F, 11.0F, -21.0F}},
        neeh::StrokeStyle("#123456", 4.0, neeh::Brush::marker, 0.75),
        std::move(id),
        author,
        created_at);
}

void test_geometry_and_style() {
    const neeh::Point point {2.0, 3.0, 4, 0.7F, 5.0F, 6.0F};
    const auto moved = point.translated(10.0, -2.0);
    CHECK(moved.x == 12.0);
    CHECK(moved.y == 1.0);
    CHECK(moved.t_ms == 4);
    CHECK(moved.pressure == point.pressure);

    const neeh::BoundingBox box(0.0, 1.0, 10.0, 11.0);
    CHECK(box.width() == 10.0);
    CHECK(box.height() == 10.0);
    CHECK(box.contains(0.0, 11.0));
    CHECK(box.contains(neeh::BoundingBox(2.0, 3.0, 4.0, 5.0)));
    CHECK(box.intersects(neeh::BoundingBox(10.0, 11.0, 12.0, 13.0)));
    CHECK(!box.intersects(neeh::BoundingBox(10.01, 11.01, 12.0, 13.0)));
    const auto expanded = box.expanded(2.0);
    CHECK(expanded.min_x() == -2.0);
    CHECK(expanded.max_y() == 13.0);
    const auto union_box = box.united(neeh::BoundingBox(-2.0, 5.0, 8.0, 20.0));
    CHECK(union_box.min_x() == -2.0);
    CHECK(union_box.max_y() == 20.0);

    CHECK(!neeh::BoundingBox::union_all({}).has_value());
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::BoundingBox(2.0, 0.0, 1.0, 3.0);
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::StrokeStyle("#000", 0.0);
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::StrokeStyle("#000", 1.0, neeh::Brush::pen, 1.1);
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::StrokeStyle("red", 1.0);
    });
    const auto highlighter = neeh::StrokeStyle::highlighter();
    CHECK(highlighter.brush() == neeh::Brush::highlighter);
    CHECK(std::abs(highlighter.opacity() - 0.35) < 1e-12);

    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Stroke(
            std::vector<neeh::Point> {{0.0, 0.0, -1}},
            neeh::StrokeStyle {});
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Stroke(
            std::vector<neeh::Point> {{0.0, 0.0, 0, 1.1F}},
            neeh::StrokeStyle {});
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Stroke(
            std::vector<neeh::Point> {{0.0, 0.0, 0, 1.0F, 91.0F}},
            neeh::StrokeStyle {});
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Stroke(
            std::vector<neeh::Point> {{0.0, 0.0, 2}, {1.0, 1.0, 1}},
            neeh::StrokeStyle {});
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Stroke(
            std::vector<neeh::Point> {{0.0, 0.0}},
            neeh::StrokeStyle {},
            "st_negative_time",
            neeh::Author::user,
            -1);
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Stroke(
            std::vector<neeh::Point> {{0.0, 0.0}},
            neeh::StrokeStyle {},
            std::string {},
            neeh::Author::user,
            0);
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Layer("", neeh::Author::user);
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Layer("ink", neeh::Author::user, std::string("  \t"));
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Page(10.0, 10.0, "#fff", std::string {});
    });
    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Document("Title", std::string(" \n"), 0);
    });
}

void test_stroke_identity_and_layer_safety() {
    const auto stroke = make_stroke();
    CHECK(stroke.duration_ms() == 20);
    const auto box = stroke.bbox();
    CHECK(box.min_x() == 10.0);
    CHECK(box.max_y() == 40.0);

    const auto translated = stroke.translated(5.0, -5.0);
    CHECK(translated.id() == stroke.id());
    CHECK(translated.author() == stroke.author());
    CHECK(translated.created_at_ms() == stroke.created_at_ms());
    CHECK(translated.points().front().x == 15.0);
    CHECK(translated.points().front().t_ms == 5);

    const auto restyled = stroke.with_style(neeh::StrokeStyle::highlighter("#ff0", 10.0));
    CHECK(restyled.id() == stroke.id());
    CHECK(restyled.points().size() == stroke.points().size());
    CHECK(restyled.points().front().x == stroke.points().front().x);
    CHECK(restyled.points().back().tilt_y == stroke.points().back().tilt_y);

    neeh::Layer layer("notes", neeh::Author::user, "ly_notes");
    layer.add(stroke);
    CHECK(layer.get("st_test") != nullptr);
    expect_error(neeh::ErrorCode::conflict, [&] { layer.add(stroke); });
    layer.set_locked(true);
    expect_error(neeh::ErrorCode::locked, [&] { (void)layer.remove("st_test"); });
    expect_error(neeh::ErrorCode::locked, [&] { layer.replace(translated); });
    layer.set_locked(false);
    CHECK(layer.replace(translated).points().front().x == 15.0);
    const auto removed = layer.remove("st_test");
    CHECK(removed.has_value());
    CHECK(!layer.remove("missing").has_value());
}

void test_document_mutation_and_queries() {
    neeh::Document document("Host Test", "doc_test", 42);
    CHECK(document.pages().size() == 1);
    auto* page = document.page(0);
    CHECK(page != nullptr);
    CHECK(page->layers().size() == 1);

    page->add_stroke(make_stroke("st_user", neeh::Author::user, 1000));
    page->add_stroke(make_stroke("st_agent", neeh::Author::agent, 2000));
    CHECK(page->layers().size() == 2);
    CHECK(page->layer(1)->author() == neeh::Author::agent);
    CHECK(page->find("st_agent")->layer_index == 1);

    CHECK(page->all_strokes().size() == 2);
    CHECK(page->strokes_since(1500).size() == 1);
    expect_error(neeh::ErrorCode::invalid_argument, [&] { (void)page->strokes_since(-1); });
    CHECK(page->strokes_in(neeh::BoundingBox(0.0, 0.0, 12.0, 22.0)).size() == 2);
    CHECK(page->content_bbox().has_value());

    page->translate_stroke("st_user", 100.0, 0.0);
    CHECK(page->find("st_user").has_value());
    CHECK(page->layer(0)->get("st_user")->bbox().min_x() == 110.0);
    page->restyle_stroke("st_user", neeh::StrokeStyle("#f00", 8.0));
    CHECK(page->layer(0)->get("st_user")->style().width() == 8.0);

    page->layer(0)->set_visible(false);
    CHECK(page->all_strokes(true).size() == 1);
    page->layer(0)->set_visible(true);
    page->layer(0)->set_locked(true);
    expect_error(neeh::ErrorCode::locked, [&] {
        page->translate_stroke("st_user", 1.0, 1.0);
    });
    page->layer(0)->set_locked(false);

    const auto removed = page->remove_stroke("st_user");
    CHECK(removed.has_value());
    CHECK(removed->id() == "st_user");
    CHECK(!page->find("st_user").has_value());
    expect_error(neeh::ErrorCode::not_found, [&] {
        page->restyle_stroke("missing", neeh::StrokeStyle {});
    });

    auto& second = document.new_page(500.0, 600.0, "#eee");
    const auto second_id = second.id();
    CHECK(document.page(second_id) != nullptr);
    CHECK(document.remove_page(second_id).has_value());
    CHECK(document.pages().size() == 1);
}

void test_renderers() {
    neeh::Page page(20.0, 20.0, "#ffffff", "pg_render");
    page.add_stroke(neeh::Stroke(
        std::vector<neeh::Point> {{2.0, 2.0, 0, 1.0F}, {18.0, 18.0, 10, 0.5F}},
        neeh::StrokeStyle("#ff0000", 2.0),
        "st_red"));
    auto& hidden = page.add_layer("hidden");
    hidden.add(neeh::Stroke(
        std::vector<neeh::Point> {{10.0, 10.0}},
        neeh::StrokeStyle("#00ff00", 4.0),
        "st_hidden"));
    hidden.set_visible(false);

    const auto svg = neeh::SvgRenderer {}.render(page);
    CHECK(svg.find("<svg") == 0);
    CHECK(svg.find("st_hidden") == std::string::npos);
    CHECK(svg.find("stroke=\"#ff0000\"") != std::string::npos);
    CHECK(svg.find("<polyline") != std::string::npos);

    neeh::SvgRenderOptions cropped;
    cropped.region = neeh::BoundingBox(5.0, 5.0, 15.0, 15.0);
    cropped.scale = 2.0;
    const auto crop_svg = neeh::SvgRenderer {}.render(page, cropped);
    CHECK(crop_svg.find("width=\"20\"") != std::string::npos);
    CHECK(crop_svg.find("viewBox=\"5 5 10 10\"") != std::string::npos);

    expect_error(neeh::ErrorCode::invalid_argument, [] {
        (void)neeh::Page(10.0, 10.0, "white");
    });

    neeh::CpuRenderOptions options;
    options.width = 40;
    options.height = 40;
    const auto image = neeh::CpuRenderer {}.render(page, options);
    CHECK(image.width() == 40);
    CHECK(image.height() == 40);
    CHECK(image.stride() == 160);
    CHECK(image.pixels().size() == 6400);
    bool found_red = false;
    for (std::size_t offset = 0; offset < image.pixels().size(); offset += 4) {
        if (image.pixels()[offset] > image.pixels()[offset + 1] + 20 &&
            image.pixels()[offset] > image.pixels()[offset + 2] + 20) {
            found_red = true;
            break;
        }
    }
    CHECK(found_red);

    neeh::Page extreme_page(10.0, 10.0);
    extreme_page.add_stroke(neeh::Stroke(
        std::vector<neeh::Point> {{-1e300, 5.0}, {1e300, 5.0}},
        neeh::StrokeStyle("#000", 1.0),
        "st_extreme"));
    options.width = 16;
    options.height = 16;
    const auto extreme_image = neeh::CpuRenderer {}.render(extreme_page, options);
    CHECK(extreme_image.pixels().size() == 16 * 16 * 4);

    options.width = 32768;
    options.height = 32768;
    expect_error(neeh::ErrorCode::invalid_argument, [&] {
        (void)neeh::CpuRenderer {}.render(page, options);
    });
}

} // namespace

int main() {
    test_geometry_and_style();
    test_stroke_identity_and_layer_safety();
    test_document_mutation_and_queries();
    test_renderers();
    if (failures != 0) {
        std::cerr << failures << " test check(s) failed\n";
        return EXIT_FAILURE;
    }
    std::cout << "portable C++ core checks passed\n";
    return EXIT_SUCCESS;
}
