#include <neeh/core.hpp>
#include <neeh/render.hpp>

#include <string>
#include <vector>

int main() {
    neeh::Page page(10.0, 10.0);
    page.add_stroke(neeh::Stroke(
        std::vector<neeh::Point> {{1.0, 1.0}, {9.0, 9.0}},
        neeh::StrokeStyle {},
        "st_install_smoke"));
    const std::string svg = neeh::SvgRenderer {}.render(page);
    return svg.find("st_install_smoke") == std::string::npos &&
                   svg.find("<polyline") != std::string::npos
               ? 0
               : 1;
}
