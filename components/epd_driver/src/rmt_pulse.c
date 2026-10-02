
/******************************************************************************/
/***        include files                                                   ***/
/******************************************************************************/

#include "rmt_pulse.h"

#include <driver/rmt_tx.h>

/******************************************************************************/
/***        macro definitions                                               ***/
/******************************************************************************/

/******************************************************************************/
/***        type definitions                                                ***/
/******************************************************************************/

/******************************************************************************/
/***        local function prototypes                                       ***/
/******************************************************************************/

/******************************************************************************/
/***        exported variables                                              ***/
/******************************************************************************/

/******************************************************************************/
/***        local variables                                                 ***/
/******************************************************************************/

/**
 * @brief the RMT TX channel handle
 */
static rmt_channel_handle_t s_row_rmt_chan;

/**
 * @brief copy encoder used to push a single pre-built RMT symbol out
 */
static rmt_encoder_handle_t s_row_rmt_copy_encoder;

/******************************************************************************/
/***        exported functions                                              ***/
/******************************************************************************/

void rmt_pulse_init(gpio_num_t pin)
{
    rmt_tx_channel_config_t chan_config = {
        .gpio_num = pin,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        // Same .1us resolution as the legacy driver's 80MHz/8 clock divider
        .resolution_hz = 10 * 1000 * 1000,
        .mem_block_symbols = 64,
        .trans_queue_depth = 4,
        .flags = {
            .invert_out = false,
            .with_dma = false,
            .allow_pd = false,
            .init_level = 0,
        },
    };
    ESP_ERROR_CHECK(rmt_new_tx_channel(&chan_config, &s_row_rmt_chan));

    rmt_copy_encoder_config_t copy_encoder_config = {};
    ESP_ERROR_CHECK(rmt_new_copy_encoder(&copy_encoder_config, &s_row_rmt_copy_encoder));

    ESP_ERROR_CHECK(rmt_enable(s_row_rmt_chan));
}


void IRAM_ATTR pulse_ckv_ticks(uint16_t high_time_ticks,
                               uint16_t low_time_ticks, bool wait)
{
    rmt_symbol_word_t rmt_mem_ptr;
    if (high_time_ticks > 0)
    {
        rmt_mem_ptr.level0 = 1;
        rmt_mem_ptr.duration0 = high_time_ticks;
        rmt_mem_ptr.level1 = 0;
        rmt_mem_ptr.duration1 = low_time_ticks;
    }
    else
    {
        rmt_mem_ptr.level0 = 1;
        rmt_mem_ptr.duration0 = low_time_ticks;
        rmt_mem_ptr.level1 = 0;
        rmt_mem_ptr.duration1 = 0;
    }

    const rmt_transmit_config_t transmit_config = {
        .loop_count = 0,
    };
    rmt_transmit(s_row_rmt_chan, s_row_rmt_copy_encoder, &rmt_mem_ptr,
                 sizeof(rmt_mem_ptr), &transmit_config);

    // rmt_transmit() only enqueues the transfer; the legacy driver's
    // rmt_write_items(..., wait) blocked internally when wait was true, so
    // reproduce that here explicitly.
    if (wait)
    {
        rmt_tx_wait_all_done(s_row_rmt_chan, -1);
    }
}


void IRAM_ATTR pulse_ckv_us(uint16_t high_time_us, uint16_t low_time_us, bool wait)
{
    pulse_ckv_ticks(10 * high_time_us, 10 * low_time_us, wait);
}


/******************************************************************************/
/***        local functions                                                 ***/
/******************************************************************************/

/******************************************************************************/
/***        END OF FILE                                                     ***/
/******************************************************************************/
