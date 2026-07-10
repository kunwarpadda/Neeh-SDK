#ifndef NEEH_RENDER_HPP
#define NEEH_RENDER_HPP

#include <neeh/core.hpp>

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace neeh {

struct NEEH_API SvgRenderOptions {
    std::optional<BoundingBox> region;
    double scale = 1.0;
};

class NEEH_API SvgRenderer final {
public:
    std::string render(const Page& page, const SvgRenderOptions& options = {}) const;
};

struct NEEH_API CpuRenderOptions {
    std::optional<BoundingBox> region;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    double scale = 1.0;
};

class NEEH_API Image final {
public:
    Image(std::uint32_t width, std::uint32_t height, std::vector<std::uint8_t> rgba);

    std::uint32_t width() const noexcept;
    std::uint32_t height() const noexcept;
    std::size_t stride() const noexcept;
    const std::vector<std::uint8_t>& pixels() const noexcept;

private:
    std::uint32_t width_;
    std::uint32_t height_;
    std::vector<std::uint8_t> pixels_;
};

class NEEH_API CpuRenderer final {
public:
    Image render(const Page& page, const CpuRenderOptions& options = {}) const;
};

} // namespace neeh

#endif
