#ifndef NEEH_EXPORT_H
#define NEEH_EXPORT_H

#if defined(_WIN32) || defined(__CYGWIN__)
#  if defined(NEEH_CORE_BUILD)
#    define NEEH_API __declspec(dllexport)
#  elif defined(NEEH_CORE_SHARED)
#    define NEEH_API __declspec(dllimport)
#  else
#    define NEEH_API
#  endif
#elif defined(__GNUC__) || defined(__clang__)
#  define NEEH_API __attribute__((visibility("default")))
#else
#  define NEEH_API
#endif

#endif
