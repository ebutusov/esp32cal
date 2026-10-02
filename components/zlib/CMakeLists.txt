
idf_component_register(SRC_DIRS "."
                        INCLUDE_DIRS ".")

# Vendored stock zlib is unmodified upstream C89-era source (K&R function
# definitions, intentional switch fallthrough, etc.) that doesn't clean
# build under IDF's default -Werror policy on newer GCC. Downgrade warnings
# to non-fatal for this component only; the rest of the project keeps -Werror.
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error)
