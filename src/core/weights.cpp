#include "core/weights.h"
#include "core/log.h"
#include <algorithm>
#include <cmath>

namespace r2c {
std::array<int16_t,kMaxWeightsPerVertex> PackWeights(const float* weights,int count) {
    if(count<1 || count>kMaxWeightsPerVertex) Fatal("invalid packed influence count %d",count);
    double total=0;
    for(int i=0;i<count;++i) {
        if(!std::isfinite(weights[i]) || weights[i]<=0) Fatal("packed skin weights must be finite and positive");
        total+=weights[i];
    }
    std::array<double,kMaxWeightsPerVertex> exact{};
    std::array<int,kMaxWeightsPerVertex> units{};
    int sum=0;
    for(int i=0;i<count;++i) {
        exact[i]=weights[i]/total*32768.;
        units[i]=std::max(1,int(std::floor(exact[i])));
        sum+=units[i];
    }
    while(sum!=32768) {
        int choice=-1; double best=-1e100;
        for(int i=0;i<count;++i) {
            if(sum>32768 && units[i]<=1) continue;
            double priority=sum<32768?exact[i]-units[i]:units[i]-exact[i];
            if(priority>best) { choice=i; best=priority; }
        }
        if(choice<0) Fatal("cannot apportion native skin weights");
        int step=sum<32768?1:-1; units[choice]+=step; sum+=step;
    }
    std::array<int16_t,kMaxWeightsPerVertex> result{};
    for(int i=0;i<count;++i) {
        if(std::fabs(units[i]/32768.-weights[i]/total)>2./32767.)
            Fatal("skin weight exceeds native quantization error budget");
        result[i]=int16_t(units[i]-1);
    }
    return result;
}
}
